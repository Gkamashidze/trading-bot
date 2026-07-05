"""Walk-forward out-of-sample edge test for the ETF basket (SPY / QQQ / SOXX).

Same honest methodology as the crypto edge test (scripts/run_walk_forward.py),
applied to decades of daily ETF data: parameters tuned only on each train
window, applied unseen to the next test window, compared to buy-and-hold over
the identical OOS span. Answers "do the strategies assigned to ETFs actually
have an edge on ETF data?" — they had never been tested on it before.

Daily bars → 252 trading days/year, train ≈ 2 years, test ≈ 6 months.

Run:  uv run python scripts/download_etf_data.py       # once, to fetch data
      uv run python scripts/run_etf_walk_forward.py
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
from trading_bot.strategies.candidates import TrendFilterStrategy  # noqa: E402
from trading_bot.strategies.rsi_mean_reversion import RsiMeanReversionStrategy  # noqa: E402
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy  # noqa: E402

_DATADIR = _ROOT / "data/raw/etf"
_OUTDIR = _ROOT / "docs/strategies/backtest_reports/etf"
_SYMBOLS = ("SPY", "QQQ", "SOXX")
_DAYS_PER_YEAR = 252  # trading days
_TRAIN_BARS = 504  # ~2 trading years
_TEST_BARS = 126  # ~6 months


def _sma_grid() -> list[dict[str, int]]:
    return [{"fast": f, "slow": s} for f in (10, 20, 50) for s in (50, 100, 200) if f < s]


def _rsi_grid() -> list[dict[str, float]]:
    return [
        {"period": p, "oversold": os, "overbought": ob}
        for p in (7, 14, 21)
        for os in (25.0, 30.0, 35.0)
        for ob in (65.0, 70.0, 75.0)
    ]


def _trend_grid() -> list[dict[str, int]]:
    # SMA regime period in DAYS (daily bars).
    return [{"period": d} for d in (20, 50, 100, 150, 200)]


def _load(symbol: str) -> pd.DataFrame:
    path = _DATADIR / f"{symbol.lower()}_1d.parquet"
    if not path.exists():
        raise SystemExit(f"missing {path}. Run scripts/download_etf_data.py first.")
    return pd.read_parquet(path).sort_values("open_time").reset_index(drop=True)


def main() -> None:
    _OUTDIR.mkdir(parents=True, exist_ok=True)
    cfg = BacktestConfig(annual_trading_days=_DAYS_PER_YEAR, fill_rng_seed=7)
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    strategies = [
        ("sma_crossover", lambda p: SmaCrossoverStrategy(**p), _sma_grid(), 5),
        ("rsi_mean_reversion", lambda p: RsiMeanReversionStrategy(**p), _rsi_grid(), 5),
        ("trend_filter", lambda p: TrendFilterStrategy(**p), _trend_grid(), 3),
    ]

    summary: list[tuple[str, str, float, float, float, float, bool]] = []
    for symbol in _SYMBOLS:
        bars = _load(symbol)
        print(
            f"\n### {symbol} — {len(bars):,} daily bars {bars['open_time'].min().date()} → {bars['open_time'].max().date()}"
        )
        for sid, factory, grid, min_trades in strategies:
            result = run_walk_forward(
                bars,
                strategy_id=f"{symbol.lower()}_{sid}",
                symbol=symbol,
                factory=factory,
                param_grid=grid,
                train_bars=_TRAIN_BARS,
                test_bars=_TEST_BARS,
                config=cfg,
                min_train_trades=min_trades,
            )
            write_reports(result, _OUTDIR, generated_at=generated_at)
            oos, bench = result.oos_metrics, result.benchmark_metrics
            summary.append(
                (
                    symbol,
                    sid,
                    oos.net_total_return_pct,
                    oos.sharpe_ratio,
                    bench.total_return_pct,
                    bench.sharpe_ratio,
                    result.beats_benchmark,
                )
            )
            print(
                f"  {sid:<20} strat {oos.net_total_return_pct:+7.1f}% Sh {oos.sharpe_ratio:5.2f} | "
                f"B&H {bench.total_return_pct:+7.1f}% Sh {bench.sharpe_ratio:5.2f} | "
                f"beats: {'YES' if result.beats_benchmark else 'no':<3} | trades {oos.total_trades}"
            )

    print("\n══ SUMMARY: does any strategy beat buy-and-hold OOS? ══")
    wins = sum(1 for *_, beats in summary if beats)
    print(f"  {wins}/{len(summary)} strategy-ETF combos beat buy-and-hold.")
    for sym, sid, sr, ssh, br, bsh, beats in summary:
        mark = "✅" if beats else "❌"
        print(
            f"  {mark} {sym:<5} {sid:<20} {sr:+7.1f}% (Sh {ssh:5.2f}) vs B&H {br:+7.1f}% (Sh {bsh:5.2f})"
        )


if __name__ == "__main__":
    sys.exit(main())
