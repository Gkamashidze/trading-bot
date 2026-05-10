"""Vectorized backtesting engine — long-only, bar-by-bar simulation.

Execution model:
  signal at bar[i]  →  trade executes at bar[i+1] open  (no lookahead)
  Fill price:  determined by the configured FillModel (default: REALISTIC)
  Fee/slippage:  tracked separately as gross vs net PnL

The default FillModelProfile is REALISTIC. Set config.fill_model_profile =
FillModelProfile.IDEAL to reproduce legacy perfect-fill behavior.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.fill_model import (
    FillModel,
    FillModelProfile,
    PerfectFillModel,
    RealisticFillModel,
)
from trading_bot.backtesting.metrics import compute_metrics
from trading_bot.backtesting.result import BacktestMetrics, BacktestResult
from trading_bot.strategies.base import StrategyBase


class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, bars: pd.DataFrame, strategy: StrategyBase) -> BacktestResult:
        n = len(bars)
        if n < strategy.min_bars_required:
            raise ValueError(f"Backtest needs {strategy.min_bars_required} bars, got {n}")

        cfg = self.config

        # Build fill model
        fill_model: FillModel
        if cfg.fill_model_profile == FillModelProfile.IDEAL:
            fill_model = PerfectFillModel()
        else:
            fill_model = RealisticFillModel.from_profile(cfg.fill_model_profile)

        rng = random.Random(cfg.fill_rng_seed)  # noqa: S311 — not used for crypto

        signals = strategy.backtest_signals(bars)
        signal_arr = signals.to_numpy()
        opens = bars["open"].to_numpy(dtype=float)
        closes = bars["close"].to_numpy(dtype=float)
        volumes = bars["volume"].to_numpy(dtype=float) if "volume" in bars.columns else np.zeros(n)

        cash = cfg.initial_capital
        units = 0.0
        position = 0
        entry_fill_price = 0.0
        trade_returns: list[float] = []

        # Cost tracking
        total_fees: float = 0.0
        total_slippage: float = 0.0
        partial_fills: int = 0
        rejected_orders: int = 0

        equity = np.empty(n, dtype=float)
        equity[0] = cash
        in_pos = np.zeros(n, dtype=bool)

        for i in range(1, n):
            sig = signal_arr[i - 1]

            if sig == "BUY" and position == 0:
                result = fill_model.simulate_buy(
                    reference_price=opens[i],
                    quantity=1.0,  # normalised — scaled by invest below
                    volume_at_price=volumes[i],
                    rng=rng,
                )
                if result.rejected:
                    rejected_orders += 1
                else:
                    invest = cash * cfg.position_size_pct
                    if result.is_partial:
                        invest *= result.filled_quantity  # filled_qty is 0-1 pct here
                        partial_fills += 1
                    units = invest / result.net_fill_price
                    total_fees += invest * (result.fee_paid / max(result.gross_value, 1e-10))
                    total_slippage += abs(result.net_fill_price - opens[i]) * units
                    cash -= invest
                    position = 1
                    entry_fill_price = result.net_fill_price

            elif sig == "SELL" and position == 1:
                result = fill_model.simulate_sell(
                    reference_price=opens[i],
                    quantity=units,
                    volume_at_price=volumes[i],
                    rng=rng,
                )
                if result.rejected:
                    rejected_orders += 1
                    # Keep position open — don't liquidate on stale quote
                else:
                    actual_qty = result.filled_quantity
                    if result.is_partial:
                        partial_fills += 1
                    gross_proceeds = actual_qty * result.gross_fill_price
                    net_proceeds = actual_qty * result.net_fill_price
                    total_fees += gross_proceeds - net_proceeds
                    total_slippage += abs(result.net_fill_price - opens[i]) * actual_qty
                    trade_returns.append(net_proceeds / (actual_qty * entry_fill_price) - 1.0)
                    cash += net_proceeds
                    units -= actual_qty
                    if units <= 0:
                        units = 0.0
                        position = 0

            in_pos[i] = position == 1
            equity[i] = cash + units * closes[i]

        # Force-close any open position at last bar close
        if position == 1 and units > 0:
            result = fill_model.simulate_sell(
                reference_price=closes[-1],
                quantity=units,
                volume_at_price=volumes[-1],
                rng=rng,
            )
            net_proceeds = units * (result.net_fill_price if not result.rejected else closes[-1])
            total_fees += max(0.0, units * closes[-1] - net_proceeds)
            trade_returns.append(net_proceeds / (units * entry_fill_price) - 1.0)
            cash += net_proceeds
            equity[-1] = cash

        dates = bars["open_time"] if "open_time" in bars.columns else pd.RangeIndex(n)
        equity_s = pd.Series(equity, index=pd.DatetimeIndex(dates))
        in_pos_s = pd.Series(in_pos, index=pd.DatetimeIndex(dates))

        base_metrics: BacktestMetrics = compute_metrics(
            equity_curve=equity_s,
            trade_returns=trade_returns,
            in_position=in_pos_s,
            annual_trading_days=cfg.annual_trading_days,
        )

        # Gross return: what the strategy would have earned with zero transaction costs
        gross_final = equity[-1] + total_fees + total_slippage
        gross_return_pct = (gross_final - cfg.initial_capital) / cfg.initial_capital * 100

        metrics = BacktestMetrics(
            **{
                f.name: getattr(base_metrics, f.name)
                for f in base_metrics.__dataclass_fields__.values()
                if f.name
                not in {
                    "total_fees_paid",
                    "total_slippage_cost",
                    "gross_total_return_pct",
                    "net_total_return_pct",
                    "partial_fills",
                    "rejected_orders",
                }
            },
            total_fees_paid=total_fees,
            total_slippage_cost=total_slippage,
            gross_total_return_pct=gross_return_pct,
            net_total_return_pct=base_metrics.total_return_pct,
            partial_fills=partial_fills,
            rejected_orders=rejected_orders,
        )

        t_col: pd.Series = (
            bars["open_time"] if "open_time" in bars.columns else bars.index.to_series()
        )
        period_start = str(t_col.iloc[0])[:10]
        period_end = str(t_col.iloc[-1])[:10]

        return BacktestResult(
            strategy_id=strategy.strategy_id,
            symbol="BTC/USDT",  # overridden by caller (runner.py)
            config=cfg,
            metrics=metrics,
            equity_curve=equity_s,
            computed_at=datetime.now(UTC),
            n_bars=n,
            period_start=period_start,
            period_end=period_end,
        )
