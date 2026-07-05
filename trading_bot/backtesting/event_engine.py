"""Event-driven bracket backtester for ATR-stop strategies (long-only).

The vectorized ``BacktestEngine`` acts only at bar boundaries on BUY/SELL
signals — it cannot model intrabar stop-loss / take-profit exits. Strategies
like Trend Pullback (STRATEGY_ROADMAP.md §3) live or die on their ATR bracket:
a 1.5*ATR stop and a 3*ATR target that can each trigger *inside* a bar.

This engine fills that gap. Given per-bar entry signals plus an ATR series, it:

  • enters at the NEXT bar open after a signal (no lookahead),
  • sizes the position by risk (risk_pct of equity / stop distance), no leverage,
  • checks each subsequent bar's high/low against stop and target intrabar,
  • pessimistically assumes the STOP fills first when a bar spans both,
  • trails the stop by ATR once price has advanced one R,
  • force-exits on regime break (trend filter off), max-hold, or end of data,
  • charges taker fees + adverse slippage on both entry and exit.

Exit reasons are recorded per trade so the exit-reason distribution (a
STRATEGY_ROADMAP.md §6.2 requirement) can be audited. Metrics reuse
``compute_metrics`` so results are directly comparable to the vectorized engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from trading_bot.backtesting.metrics import compute_metrics
from trading_bot.backtesting.result import BacktestMetrics

# Exit reason labels (STRATEGY_ROADMAP.md §6.1 catalogue).
EXIT_STOP = "stop_loss"
EXIT_TRAIL = "trailing_stop"
EXIT_TAKE_PROFIT = "take_profit"
EXIT_MAX_HOLD = "max_holding"
EXIT_REGIME = "regime_change"
EXIT_END = "end_of_data"


@dataclass(frozen=True)
class BracketConfig:
    """Parameters for the ATR bracket + risk sizing."""

    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    trail_atr_mult: float = 1.0
    trail_activate_r: float = 1.0  # start trailing after +1R unrealised
    max_hold_bars: int = 48  # 48h on 1h bars
    risk_per_trade_pct: float = 0.01  # 1% of equity risked per trade
    fee_rate: float = 0.001  # taker fee each side
    slippage_rate: float = 0.0005  # adverse slippage each side
    initial_capital: float = 10_000.0
    annual_periods: int = 8760  # 1h bars → hours per year


@dataclass(frozen=True)
class Trade:
    """One completed round-trip."""

    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    quantity: float
    net_return_pct: float  # fraction, net of fees + slippage
    r_multiple: float  # realised PnL / initial risk
    exit_reason: str
    bars_held: int


@dataclass(frozen=True)
class BracketResult:
    """Backtest output: metrics + trades + equity curve."""

    metrics: BacktestMetrics
    trades: list[Trade]
    equity_curve: pd.Series
    exit_reason_counts: dict[str, int] = field(default_factory=dict)


def run_bracket_backtest(
    bars: pd.DataFrame,
    entries: pd.Series,
    atr_series: pd.Series,
    trend_active: pd.Series,
    config: BracketConfig | None = None,
) -> BracketResult:
    """Run the event-driven bracket backtest.

    Args:
        bars: OHLCV frame with ``open``/``high``/``low``/``close`` and
            ``open_time`` columns, sorted oldest-first.
        entries: bool Series aligned to ``bars`` — True on a bar means "enter at
            the next bar's open" (if flat).
        atr_series: ATR aligned to ``bars`` (same units as price).
        trend_active: bool Series aligned to ``bars`` — regime filter. When it
            turns False while in a position, the position is exited at the next
            open (regime_change).
        config: bracket parameters.
    """
    cfg = config or BracketConfig()
    n = len(bars)
    if n == 0:
        raise ValueError("empty bars")

    opens = bars["open"].to_numpy(dtype=float)
    highs = bars["high"].to_numpy(dtype=float)
    lows = bars["low"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    times = bars["open_time"].to_numpy() if "open_time" in bars.columns else np.arange(n)
    entry_arr = entries.to_numpy(dtype=bool)
    atr_arr = atr_series.to_numpy(dtype=float)
    trend_arr = trend_active.to_numpy(dtype=bool)

    fee = cfg.fee_rate
    slip = cfg.slippage_rate

    equity = cfg.initial_capital
    equity_curve = np.empty(n, dtype=float)
    in_pos = np.zeros(n, dtype=bool)

    trades: list[Trade] = []
    trade_returns: list[float] = []

    # Position state
    position = False
    entry_fill = 0.0
    qty = 0.0
    stop_price = 0.0
    target_price = 0.0
    initial_risk_price = 0.0  # per-unit stop distance at entry
    bars_held = 0
    entry_idx = 0
    trailing = False  # stop has been raised by trailing logic
    peak_price = 0.0
    atr_at_entry = 0.0

    def _record_exit(idx: int, raw_exit: float, reason: str) -> None:
        nonlocal equity, position, qty, trailing
        exit_fill = raw_exit * (1.0 - slip)
        gross_proceeds = qty * exit_fill
        exit_fee = gross_proceeds * fee
        net_proceeds = gross_proceeds - exit_fee
        cost_basis = qty * entry_fill
        net_return = net_proceeds / cost_basis - 1.0 if cost_basis > 0 else 0.0
        # Realised PnL in price terms per unit, over the initial per-unit risk.
        r_mult = (exit_fill - entry_fill) / initial_risk_price if initial_risk_price > 0 else 0.0
        # Cash-basis accounting: the cost basis was removed from `equity` at
        # entry, so returning the sale proceeds closes the loop.
        equity += net_proceeds
        trades.append(
            Trade(
                entry_time=pd.Timestamp(times[entry_idx]),
                exit_time=pd.Timestamp(times[idx]),
                entry_price=entry_fill,
                exit_price=exit_fill,
                quantity=qty,
                net_return_pct=net_return,
                r_multiple=r_mult,
                exit_reason=reason,
                bars_held=bars_held,
            )
        )
        trade_returns.append(net_return)
        position = False
        qty = 0.0
        trailing = False

    for i in range(n):
        # ── Manage an open position at bar i ─────────────────────────────────
        if position:
            bars_held += 1

            # Regime break → exit at this bar's open.
            if not trend_arr[i]:
                _record_exit(i, opens[i], EXIT_REGIME)
            else:
                bar_low = lows[i]
                bar_high = highs[i]
                # Pessimistic ordering: stop before target when a bar spans both.
                if bar_low <= stop_price:
                    reason = EXIT_TRAIL if trailing else EXIT_STOP
                    _record_exit(i, stop_price, reason)
                elif bar_high >= target_price:
                    _record_exit(i, target_price, EXIT_TAKE_PROFIT)
                elif bars_held >= cfg.max_hold_bars:
                    _record_exit(i, closes[i], EXIT_MAX_HOLD)
                else:
                    # Trailing: once price advanced >= trail_activate_r * R, raise
                    # the stop to peak - trail_mult * ATR(at entry). Update using
                    # this bar's high (realised), applied to FUTURE bars only.
                    peak_price = max(peak_price, bar_high)
                    advance_r = (
                        (peak_price - entry_fill) / initial_risk_price
                        if initial_risk_price > 0
                        else 0.0
                    )
                    if advance_r >= cfg.trail_activate_r:
                        new_stop = peak_price - cfg.trail_atr_mult * atr_at_entry
                        if new_stop > stop_price:
                            stop_price = new_stop
                            trailing = True

        # ── Consider a new entry: signal on bar i-1 → enter at bar i open ─────
        if not position and i >= 1 and entry_arr[i - 1] and trend_arr[i]:
            a = atr_arr[i]
            px_open = opens[i]
            if np.isfinite(a) and a > 0 and px_open > 0:
                entry_fill = px_open * (1.0 + slip)
                risk_price = cfg.sl_atr_mult * a
                risk_amount = equity * cfg.risk_per_trade_pct
                raw_qty = risk_amount / risk_price
                # No leverage: cap notional at current equity (minus entry fee).
                max_qty = equity / (entry_fill * (1.0 + fee))
                qty = min(raw_qty, max_qty)
                if qty > 0:
                    entry_fee = qty * entry_fill * fee
                    # Remove the cash used to buy (cost basis) + entry fee.
                    equity -= qty * entry_fill + entry_fee
                    position = True
                    initial_risk_price = risk_price
                    atr_at_entry = a
                    stop_price = entry_fill - risk_price
                    target_price = entry_fill + cfg.tp_atr_mult * a
                    peak_price = entry_fill
                    bars_held = 0
                    entry_idx = i
                    trailing = False

        # Mark-to-market equity at bar close: remaining cash + position value.
        if position:
            equity_curve[i] = equity + qty * closes[i]
        else:
            equity_curve[i] = equity
        in_pos[i] = position

    # Force-close at the last bar's close.
    if position:
        _record_exit(n - 1, closes[-1], EXIT_END)
        equity_curve[-1] = equity

    dates = pd.DatetimeIndex(times)
    equity_s = pd.Series(equity_curve, index=dates)
    in_pos_s = pd.Series(in_pos, index=dates)

    metrics = compute_metrics(
        equity_curve=equity_s,
        trade_returns=trade_returns,
        in_position=in_pos_s,
        annual_trading_days=cfg.annual_periods,
    )

    reason_counts: dict[str, int] = {}
    for t in trades:
        reason_counts[t.exit_reason] = reason_counts.get(t.exit_reason, 0) + 1

    return BracketResult(
        metrics=metrics,
        trades=trades,
        equity_curve=equity_s,
        exit_reason_counts=reason_counts,
    )


def buy_and_hold_equity(bars: pd.DataFrame, initial_capital: float = 10_000.0) -> pd.Series:
    """Buy-and-hold equity curve: all-in at first open, marked to close.

    Fee-neutral baseline (one entry, held to the end) — the honest bar every
    tactical strategy must clear on a risk-adjusted basis.
    """
    opens = bars["open"].to_numpy(dtype=float)
    closes = bars["close"].to_numpy(dtype=float)
    times = bars["open_time"].to_numpy() if "open_time" in bars.columns else np.arange(len(bars))
    entry = opens[0]
    units = initial_capital / entry
    curve = units * closes
    return pd.Series(curve, index=pd.DatetimeIndex(times))
