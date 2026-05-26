"""ETF CLI command implementations.

Each function is called by trading_bot/cli/__init__.py and is also importable
directly for use in scripts and notebooks.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal

import numpy as np
import pandas as pd

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.fill_model import FillModelProfile
from trading_bot.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy

# Per-symbol strategy params (must stay in sync with base.yaml etf_strategy_params)
_SYMBOL_PARAMS: dict[str, dict[str, float | int]] = {
    "SPY": {"sma_fast": 20, "sma_slow": 50, "rsi_period": 14, "rsi_os": 32.0, "rsi_ob": 68.0},
    "QQQ": {"sma_fast": 15, "sma_slow": 40, "rsi_period": 14, "rsi_os": 30.0, "rsi_ob": 70.0},
    "SOXX": {"sma_fast": 10, "sma_slow": 30, "rsi_period": 14, "rsi_os": 28.0, "rsi_ob": 72.0},
    "IBIT": {"sma_fast": 10, "sma_slow": 25, "rsi_period": 14, "rsi_os": 25.0, "rsi_ob": 75.0},
}
_DEFAULT_PARAMS: dict[str, float | int] = {
    "sma_fast": 20,
    "sma_slow": 50,
    "rsi_period": 14,
    "rsi_os": 30.0,
    "rsi_ob": 70.0,
}
_BASE_PRICES: dict[str, float] = {"SPY": 450.0, "QQQ": 370.0, "SOXX": 190.0, "IBIT": 35.0}

_ETF_CONFIG = BacktestConfig(
    initial_capital=100_000.0,
    fee_rate=0.0,  # Alpaca is commission-free
    slippage_rate=0.0005,
    annual_trading_days=252,
    fill_model_profile=FillModelProfile.IDEAL,
    fill_rng_seed=42,
)


# ---------------------------------------------------------------------------
# Synthetic test
# ---------------------------------------------------------------------------


def _make_synthetic_bars(symbol: str, n_bars: int = 500, seed: int = 42) -> pd.DataFrame:
    base = _BASE_PRICES.get(symbol, 100.0)
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 8 * 2 * np.pi, n_bars)
    amplitude = base * 0.35
    closes = base + amplitude * np.sin(t) + rng.normal(0, base * 0.003, n_bars)
    closes = np.maximum(closes, base * 0.05)
    opens = closes + rng.normal(0, base * 0.002, n_bars)
    highs = np.maximum(closes, opens) + rng.uniform(0, base * 0.004, n_bars)
    lows = np.minimum(closes, opens) - rng.uniform(0, base * 0.004, n_bars)
    dates = pd.date_range(start="2023-01-03", periods=n_bars, freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": rng.uniform(1e6, 1e7, n_bars),
            "symbol": symbol,
            "exchange": "alpaca",
            "timeframe": "1d",
        }
    )


def run_test_synthetic(
    symbols: list[str],
    min_cycles: int = 5,
    strategy: str = "both",
) -> bool:
    """Run in-memory synthetic forced-trade tests. Returns True if all pass."""
    print(f"\n{'=' * 60}")
    print(f"Synthetic ETF Forced-Cycle Test  (min_cycles={min_cycles})")
    print(f"Symbols: {', '.join(symbols)}  |  Strategy: {strategy}")
    print("=" * 60)

    all_pass = True
    engine = BacktestEngine(config=_ETF_CONFIG)

    for sym in symbols:
        p = {**_DEFAULT_PARAMS, **_SYMBOL_PARAMS.get(sym, {})}
        bars_df = _make_synthetic_bars(sym)
        print(f"\n── {sym} ──")

        if strategy in ("sma", "both"):
            strat = SmaCrossoverStrategy(fast=int(p["sma_fast"]), slow=int(p["sma_slow"]))
            sigs = strat.backtest_signals(bars_df)
            n_buy = int((sigs == "BUY").sum())
            n_sell = int((sigs == "SELL").sum())
            result = engine.run(bars_df, strat, dataset_snapshot_id="")
            m = result.metrics
            ok_buy = n_buy >= min_cycles
            ok_sell = n_sell >= min_cycles
            ok_trades = m.total_trades >= max(1, min_cycles - 1)
            status = "PASS" if (ok_buy and ok_sell and ok_trades) else "FAIL"
            if not (ok_buy and ok_sell and ok_trades):
                all_pass = False
            print(
                f"  SMA({p['sma_fast']},{p['sma_slow']})  "
                f"buys={n_buy} {'✓' if ok_buy else '✗'}  "
                f"sells={n_sell} {'✓' if ok_sell else '✗'}  "
                f"trades={m.total_trades} {'✓' if ok_trades else '✗'}  "
                f"win%={m.win_rate:.0f}  ret%={m.total_return_pct:+.1f}  "
                f"maxDD%={m.max_drawdown_pct:.1f}  [{status}]"
            )

        if strategy in ("rsi", "both"):
            strat_rsi = RsiMeanReversionStrategy(
                period=int(p["rsi_period"]),
                oversold=float(p["rsi_os"]),
                overbought=float(p["rsi_ob"]),
            )
            sigs = strat_rsi.backtest_signals(bars_df)
            n_buy = int((sigs == "BUY").sum())
            n_sell = int((sigs == "SELL").sum())
            result = engine.run(bars_df, strat_rsi, dataset_snapshot_id="")
            m = result.metrics
            ok_buy = n_buy >= min_cycles
            ok_sell = n_sell >= min_cycles
            ok_trades = m.total_trades >= max(1, min_cycles - 1)
            status = "PASS" if (ok_buy and ok_sell and ok_trades) else "FAIL"
            if not (ok_buy and ok_sell and ok_trades):
                all_pass = False
            print(
                f"  RSI({p['rsi_period']},{p['rsi_os']},{p['rsi_ob']})  "
                f"buys={n_buy} {'✓' if ok_buy else '✗'}  "
                f"sells={n_sell} {'✓' if ok_sell else '✗'}  "
                f"trades={m.total_trades} {'✓' if ok_trades else '✗'}  "
                f"win%={m.win_rate:.0f}  ret%={m.total_return_pct:+.1f}  "
                f"maxDD%={m.max_drawdown_pct:.1f}  [{status}]"
            )

    print(f"\n{'=' * 60}")
    print(f"Result: {'ALL PASS' if all_pass else 'FAILED'}")
    print("=" * 60)
    return all_pass


# ---------------------------------------------------------------------------
# Historical backtest via yfinance
# ---------------------------------------------------------------------------


def run_backtest(
    symbols: list[str],
    start: str = "2024-01-01",
    end: str = "2025-01-01",
    strategy: str = "both",
    capital: float = 100_000.0,
) -> None:
    """Download real ETF data via yfinance and run the backtesting engine."""
    try:
        import yfinance as yf
    except ImportError:
        print("ERROR: yfinance not installed. Run: uv add yfinance")
        sys.exit(1)

    config = BacktestConfig(
        initial_capital=capital,
        fee_rate=0.0,
        slippage_rate=0.0005,
        annual_trading_days=252,
        fill_model_profile=FillModelProfile.REALISTIC,
        fill_rng_seed=42,
    )
    engine = BacktestEngine(config=config)

    print(f"\n{'=' * 60}")
    print(f"Historical ETF Backtest  ({start} → {end})")
    print(f"Symbols: {', '.join(symbols)}  |  Capital: ${capital:,.0f}")
    print("=" * 60)

    combined_trades = 0
    combined_wins = 0

    for sym in symbols:
        p = {**_DEFAULT_PARAMS, **_SYMBOL_PARAMS.get(sym, {})}
        print(f"\n── {sym} ──")

        try:
            raw = yf.download(sym, start=start, end=end, progress=False, auto_adjust=True)
        except Exception as exc:
            print(f"  ERROR: yfinance download failed: {exc}")
            continue

        if raw.empty or len(raw) < 60:
            print(f"  SKIP: insufficient data ({len(raw)} bars)")
            continue

        # Flatten multi-level columns if present (yfinance quirk)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.droplevel(1)

        bars_df = pd.DataFrame(
            {
                "open_time": pd.to_datetime(raw.index, utc=True),
                "open": raw["Open"].values,
                "high": raw["High"].values,
                "low": raw["Low"].values,
                "close": raw["Close"].values,
                "volume": raw["Volume"].values,
                "symbol": sym,
                "exchange": "alpaca",
                "timeframe": "1d",
            }
        )

        strategies_to_run: list[SmaCrossoverStrategy | RsiMeanReversionStrategy] = []
        if strategy in ("sma", "both"):
            strategies_to_run.append(
                SmaCrossoverStrategy(fast=int(p["sma_fast"]), slow=int(p["sma_slow"]))
            )
        if strategy in ("rsi", "both"):
            strategies_to_run.append(
                RsiMeanReversionStrategy(
                    period=int(p["rsi_period"]),
                    oversold=float(p["rsi_os"]),
                    overbought=float(p["rsi_ob"]),
                )
            )

        for strat in strategies_to_run:
            try:
                sigs = strat.backtest_signals(bars_df)
                n_buy = int((sigs == "BUY").sum())
                n_sell = int((sigs == "SELL").sum())
                result = engine.run(bars_df, strat, dataset_snapshot_id="")
                m = result.metrics
                combined_trades += m.total_trades
                combined_wins += m.winning_trades
                print(
                    f"  {strat.strategy_id:20s}  "
                    f"buys={n_buy:3d}  sells={n_sell:3d}  "
                    f"trades={m.total_trades:3d}  "
                    f"wins={m.winning_trades:3d}  "
                    f"win%={m.win_rate:5.1f}  "
                    f"ret%={m.total_return_pct:+7.2f}  "
                    f"maxDD%={m.max_drawdown_pct:6.2f}  "
                    f"sharpe={m.sharpe_ratio:.2f}"
                )
            except Exception as exc:
                print(f"  {strat.strategy_id}: ERROR — {exc}")

    print(f"\n{'─' * 60}")
    combined_wr = (combined_wins / combined_trades * 100) if combined_trades else 0.0
    print(f"COMBINED  trades={combined_trades}  wins={combined_wins}  win%={combined_wr:.1f}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Paper execution test (async)
# ---------------------------------------------------------------------------


async def run_paper_execution(symbols: list[str], qty: float = 1.0) -> None:
    """Submit a test order to Alpaca paper API for each symbol, then cancel it."""
    from trading_bot.core.exceptions import ExchangeOrderError
    from trading_bot.core.models import ExchangeId, OrderRequest, OrderSide, OrderType, TimeInForce
    from trading_bot.exchange.alpaca import AlpacaExchange

    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        print("ERROR: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set.")
        sys.exit(1)

    adapter = AlpacaExchange(
        api_key=api_key,
        secret_key=secret_key,
        paper=True,
        allowed_symbols=frozenset(symbols),
        allow_live_trading=False,
    )

    print(f"\n{'=' * 60}")
    print("Alpaca Paper Execution Test")
    print(f"Symbols: {', '.join(symbols)}  |  Qty: {qty} share(s)")
    print("NOTE: paper=True — no real money involved")
    print("=" * 60)

    healthy = await adapter.health_check()
    if not healthy:
        print("ERROR: Alpaca paper account health check failed.")
        sys.exit(1)
    print("Health check: PASS")

    for sym in symbols:
        print(f"\n── {sym} ──")
        req = OrderRequest(
            symbol=sym,
            exchange=ExchangeId.ALPACA,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal(str(qty)),
            time_in_force=TimeInForce.DAY,
            strategy_id="paper_execution_cli_test",
        )
        try:
            result = await adapter.place_order(req)
            oid = result["exchange_order_id"]
            print(f"  Order submitted: id={oid}  status={result['status']}")
            # Immediately cancel
            try:
                cancel = await adapter.cancel_order(oid, sym)
                print(f"  Order cancelled: {cancel['status']}")
            except ExchangeOrderError as ce:
                print(f"  Cancel note: {ce} (order may have been filled already)")
        except ExchangeOrderError as exc:
            if "market is closed" in str(exc):
                print(f"  SKIP: market is closed — {exc}")
            else:
                print(f"  ERROR: {exc}")

    print(f"\n{'=' * 60}")
    print("Paper execution test complete.")
    print("=" * 60)
