"""Multi-asset / multi-split validation of SentimentTrendHybridStrategy.

The hybrid beat buy-and-hold on a risk-adjusted basis on BTC (see
docs/strategies/backtest_reports/sentiment/). One asset, one split is not proof.
This runs the SAME walk-forward on BTC and ETH across three train/test window
sizes and reports whether the Sharpe + drawdown edge survives - the difference
between a genuine effect and a BTC-history overfit.

Run:  uv run python scripts/download_signal_data.py       # fetches BTC + ETH
      uv run python scripts/validate_sentiment_hybrid.py
"""
# ruff: noqa: E501 - CLI summary lines are formatted for terminal readability

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from trading_bot.backtesting.config import BacktestConfig  # noqa: E402
from trading_bot.backtesting.walk_forward import run_walk_forward  # noqa: E402
from trading_bot.strategies.sentiment import SentimentTrendHybridStrategy  # noqa: E402

_SIGDIR = _ROOT / "data/raw/signals"
_ASSETS = ("btc", "eth")
# (train_bars, test_bars) - ~2y/6m, ~1y/3m, ~3y/6m.
_SPLITS = ((504, 126), (365, 90), (730, 180))


def _grid() -> list[dict[str, float]]:
    return [
        {"funding_below": b, "exit_ma": ma}
        for b in (-0.0001, 0.0, 0.0001)
        for ma in (20, 50, 100, 200)
    ]


def main() -> None:
    grid = _grid()
    rows: list[tuple[str, str, float, float, float, float, float, float]] = []

    for asset in _ASSETS:
        path = _SIGDIR / f"{asset}_daily_signals.parquet"
        if not path.exists():
            raise SystemExit(f"missing {path}. Run scripts/download_signal_data.py first.")
        bars = pd.read_parquet(path).sort_values("open_time").reset_index(drop=True)
        cfg = BacktestConfig(annual_trading_days=365, fill_rng_seed=7)

        for train_bars, test_bars in _SPLITS:
            result = run_walk_forward(
                bars,
                strategy_id=f"{asset}_hybrid",
                symbol=asset.upper(),
                factory=lambda p: SentimentTrendHybridStrategy(**p),
                param_grid=grid,
                train_bars=train_bars,
                test_bars=test_bars,
                config=cfg,
                min_train_trades=3,
            )
            o, b = result.oos_metrics, result.benchmark_metrics
            rows.append(
                (
                    asset.upper(),
                    f"{train_bars}/{test_bars}",
                    o.net_total_return_pct,
                    o.sharpe_ratio,
                    o.max_drawdown_pct,
                    b.total_return_pct,
                    b.sharpe_ratio,
                    b.max_drawdown_pct,
                )
            )

    print(
        f"\n{'asset':<6}{'split':<10}{'strat ret%':>11}{'Sh':>6}{'DD%':>8}  |{'B&H ret%':>11}{'Sh':>6}{'DD%':>8}  edge"
    )
    sharpe_wins = 0
    for asset, split, sr, ssh, sdd, br, bsh, bdd in rows:
        beats_sharpe = ssh > bsh
        beats_dd = abs(sdd) < abs(bdd)
        edge = (
            "Sharpe+DD"
            if (beats_sharpe and beats_dd)
            else ("Sharpe" if beats_sharpe else ("DD" if beats_dd else "-"))
        )
        sharpe_wins += 1 if beats_sharpe else 0
        print(
            f"{asset:<6}{split:<10}{sr:>10.1f}%{ssh:>6.2f}{sdd:>7.1f}%  |{br:>10.1f}%{bsh:>6.2f}{bdd:>7.1f}%  {edge}"
        )

    print(f"\nSharpe beats buy-and-hold in {sharpe_wins}/{len(rows)} asset-split combos.")
    if sharpe_wins == len(rows):
        print(
            "→ Risk-adjusted edge holds across BOTH assets and ALL splits - robust, not a BTC overfit."
        )
    elif sharpe_wins >= len(rows) * 0.6:
        print("→ Edge holds in most combos - promising but check the misses.")
    else:
        print("→ Edge does NOT generalise - likely a BTC-specific artifact.")


if __name__ == "__main__":
    sys.exit(main())
