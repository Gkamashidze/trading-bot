"""Walk-forward OOS test for non-price sentiment/positioning strategies on BTC.

The last honest place to look for edge after price-based strategies all failed:
crowd sentiment (Fear & Greed) and derivatives positioning (funding rate). Same
methodology as every other edge test — in-sample tuning, unseen test windows,
buy-and-hold benchmark over the identical OOS span.

Daily BTC bars + merged signals (scripts/download_signal_data.py). 365-day
annualisation (crypto trades every day), train ~2y, test ~6mo.

Run:  uv run python scripts/download_signal_data.py       # once, to fetch data
      uv run python scripts/run_sentiment_walk_forward.py
"""
# ruff: noqa: E501 — CLI summary lines are formatted for terminal readability

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from trading_bot.backtesting.config import BacktestConfig  # noqa: E402
from trading_bot.backtesting.walk_forward import run_walk_forward  # noqa: E402
from trading_bot.backtesting.wf_report import write_reports  # noqa: E402
from trading_bot.strategies.sentiment import (  # noqa: E402
    FearGreedContrarianStrategy,
    FundingContrarianStrategy,
    SentimentTrendHybridStrategy,
)

_DATA = _ROOT / "data/raw/signals/btc_daily_signals.parquet"
_OUTDIR = _ROOT / "docs/strategies/backtest_reports/sentiment"
_DAYS_PER_YEAR = 365
_TRAIN_BARS = 504  # ~2 years of daily bars
_TEST_BARS = 126  # ~6 months


def _fng_grid() -> list[dict[str, float]]:
    return [
        {"buy_below": b, "sell_above": s}
        for b in (20.0, 25.0, 30.0, 35.0)
        for s in (55.0, 60.0, 65.0, 70.0, 75.0)
    ]


def _funding_grid() -> list[dict[str, float]]:
    return [
        {"buy_below": b, "sell_above": s}
        for b in (-0.0002, -0.0001, 0.0, 0.0001)
        for s in (0.0002, 0.0003, 0.0005)
    ]


def _hybrid_grid() -> list[dict[str, float]]:
    return [
        {"funding_below": b, "exit_ma": ma}
        for b in (-0.0001, 0.0, 0.0001)
        for ma in (20, 50, 100, 200)
    ]


def _load() -> pd.DataFrame:
    if not _DATA.exists():
        raise SystemExit(f"missing {_DATA}. Run scripts/download_signal_data.py first.")
    return pd.read_parquet(_DATA).sort_values("open_time").reset_index(drop=True)


def main() -> None:
    _OUTDIR.mkdir(parents=True, exist_ok=True)
    bars = _load()
    cfg = BacktestConfig(annual_trading_days=_DAYS_PER_YEAR, fill_rng_seed=7)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    print(
        f"loaded {len(bars):,} daily bars {bars['open_time'].min().date()} → {bars['open_time'].max().date()}"
    )

    specs = [
        ("fear_greed_contrarian", lambda p: FearGreedContrarianStrategy(**p), _fng_grid(), 3),
        ("funding_contrarian", lambda p: FundingContrarianStrategy(**p), _funding_grid(), 3),
        ("sentiment_trend_hybrid", lambda p: SentimentTrendHybridStrategy(**p), _hybrid_grid(), 3),
    ]

    summary = []
    for sid, factory, grid, min_trades in specs:
        result = run_walk_forward(
            bars,
            strategy_id=sid,
            symbol="BTC/USDT",
            factory=factory,
            param_grid=grid,
            train_bars=_TRAIN_BARS,
            test_bars=_TEST_BARS,
            config=cfg,
            min_train_trades=min_trades,
        )
        write_reports(result, _OUTDIR, generated_at=generated_at)
        oos, bench = result.oos_metrics, result.benchmark_metrics
        summary.append((sid, oos, bench, result.beats_benchmark))
        print(
            f"\n=== {sid} ({len(result.windows)} windows, {result.oos_start}→{result.oos_end}) ==="
        )
        print(
            f"  strategy : {oos.net_total_return_pct:+.1f}%  Sharpe {oos.sharpe_ratio:.2f}  maxDD {oos.max_drawdown_pct:.1f}%  trades {oos.total_trades}  win {oos.win_rate:.0f}%"
        )
        print(
            f"  buy&hold : {bench.total_return_pct:+.1f}%  Sharpe {bench.sharpe_ratio:.2f}  maxDD {bench.max_drawdown_pct:.1f}%"
        )
        print(f"  beats B&H: {'YES' if result.beats_benchmark else 'NO'}")

    print("\n══ SUMMARY ══")
    for sid, oos, bench, beats in summary:
        mark = "✅" if beats else "❌"
        print(
            f"  {mark} {sid:<24} {oos.net_total_return_pct:+8.1f}% (Sh {oos.sharpe_ratio:5.2f}) vs B&H {bench.total_return_pct:+8.1f}% (Sh {bench.sharpe_ratio:5.2f})"
        )


if __name__ == "__main__":
    sys.exit(main())
