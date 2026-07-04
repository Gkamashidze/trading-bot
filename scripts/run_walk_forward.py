"""Reproducible walk-forward / out-of-sample backtest for every baseline strategy.

Reads BTC/USDT 1h history from Parquet (download first with
scripts/download_backtest_data.py), runs a rolling walk-forward with in-sample
parameter optimisation, and writes honest per-strategy reports to
docs/strategies/backtest_reports/.

Run:  python scripts/run_walk_forward.py
"""
# ruff: noqa: E501 — CLI summary lines are formatted for terminal readability

from __future__ import annotations

import glob
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from trading_bot.backtesting.config import BacktestConfig  # noqa: E402
from trading_bot.backtesting.walk_forward import run_walk_forward  # noqa: E402
from trading_bot.backtesting.wf_report import write_reports  # noqa: E402
from trading_bot.strategies.rsi_mean_reversion import RsiMeanReversionStrategy  # noqa: E402
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy  # noqa: E402

_DATA_GLOB = str(_ROOT / "data/raw/binance/BTC_USDT/1h/*.parquet")
_OUTDIR = _ROOT / "docs/strategies/backtest_reports"
_HOURS_PER_YEAR = 24 * 365  # correct annualisation for 1h bars

# Train ~180 days, test ~30 days (hourly bars).
_TRAIN_BARS = 24 * 180
_TEST_BARS = 24 * 30


def _sma_grid() -> list[dict[str, int]]:
    grid = []
    for fast in (10, 15, 20, 30, 50):
        for slow in (50, 100, 150, 200):
            if fast < slow:
                grid.append({"fast": fast, "slow": slow})
    return grid


def _rsi_grid() -> list[dict[str, float]]:
    grid = []
    for period in (7, 14, 21):
        for oversold in (20.0, 25.0, 30.0):
            for overbought in (70.0, 75.0, 80.0):
                grid.append({"period": period, "oversold": oversold, "overbought": overbought})
    return grid


def _load_bars() -> pd.DataFrame:
    files = sorted(glob.glob(_DATA_GLOB))
    if not files:
        raise SystemExit(f"No data at {_DATA_GLOB}. Run scripts/download_backtest_data.py first.")
    df = pd.concat([pd.read_parquet(f) for f in files])
    return df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)


def main() -> None:
    bars = _load_bars()
    cfg = BacktestConfig(annual_trading_days=_HOURS_PER_YEAR, fill_rng_seed=7)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    specs = [
        ("sma_crossover", "SMA", lambda p: SmaCrossoverStrategy(**p), _sma_grid()),
        (
            "rsi_mean_reversion",
            "RSI",
            lambda p: RsiMeanReversionStrategy(**p),
            _rsi_grid(),
        ),
    ]

    print(f"Loaded {len(bars)} bars {bars['open_time'].min()} -> {bars['open_time'].max()}\n")
    for strategy_id, _label, factory, grid in specs:
        result = run_walk_forward(
            bars,
            strategy_id=strategy_id,
            symbol="BTC/USDT",
            factory=factory,
            param_grid=grid,
            train_bars=_TRAIN_BARS,
            test_bars=_TEST_BARS,
            config=cfg,
        )
        paths = write_reports(result, _OUTDIR, generated_at=generated_at)
        oos, bench = result.oos_metrics, result.benchmark_metrics
        reports = ", ".join(str(p.relative_to(_ROOT)) for p in paths)
        print(
            f"=== {strategy_id} ({len(result.windows)} windows, {result.oos_start}→{result.oos_end}) ==="
        )
        print(
            f"  strategy : {oos.net_total_return_pct:+.1f}%  Sharpe {oos.sharpe_ratio:.2f}  maxDD {oos.max_drawdown_pct:.1f}%"
        )
        print(
            f"  buy&hold : {bench.total_return_pct:+.1f}%  Sharpe {bench.sharpe_ratio:.2f}  maxDD {bench.max_drawdown_pct:.1f}%"
        )
        print(
            f"  beats B&H: {'YES' if result.beats_benchmark else 'NO'}  |  trades {oos.total_trades}  win {oos.win_rate:.0f}%  fees ${oos.total_fees_paid:.0f}"
        )
        print(f"  reports  : {reports}\n")


if __name__ == "__main__":
    main()
