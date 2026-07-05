"""Walk-forward out-of-sample research: Trend Pullback vs buy-and-hold on BTC/USDT.

Honest proof-of-edge harness for the STRATEGY_ROADMAP.md §3 Trend Pullback design:

  • Rolling walk-forward: parameters are optimised on each TRAIN window (in-sample
    Sharpe, with a minimum trade count) and applied UNSEEN to the next TEST window.
  • OOS test segments are stitched into one continuous equity curve, carrying
    capital forward — no peeking, no survivorship, no per-window cherry-picking.
  • Reports total return, Sharpe, Sortino, Calmar, max drawdown, trade count and
    the exit-reason distribution, side by side with buy-and-hold over the same
    OOS span (the real bar for a long-only tactical strategy is risk-adjusted).

Run:  uv run python scripts/research_trend_pullback.py
"""

from __future__ import annotations

import argparse
import itertools
import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from trading_bot.backtesting.event_engine import (  # noqa: E402
    BracketConfig,
    BracketResult,
    buy_and_hold_equity,
    run_bracket_backtest,
)
from trading_bot.backtesting.metrics import compute_metrics  # noqa: E402
from trading_bot.strategies.trend_pullback import (  # noqa: E402
    TrendPullbackParams,
    compute_trend_pullback_signals,
)

_DATA = _ROOT / "data/raw/binance/BTC_USDT/1h/btc_usdt_1h_2022_2026.parquet"

# Warm-up: daily SMA200 needs ~200 daily bars ≈ 200 days ≈ 4800 1h bars.
_WARMUP_BARS = 4800
_TRAIN_BARS = 8760  # ~12 months of 1h bars
_TEST_BARS = 4380  # ~6 months
_MIN_TRAIN_TRADES = 8

# Parameter grid (kept small for tractable, honest optimisation).
_PARAM_GRID = {
    "oversold_level": [30.0, 35.0],
    "sl_atr_mult": [1.0, 1.5, 2.0],
    "tp_atr_mult": [2.0, 3.0, 4.0],
}

# Toggled by the --h4 CLI flag: require last-closed 4h bar above its EMA (§4).
_USE_4H = False


def _load_bars() -> pd.DataFrame:
    if not _DATA.exists():
        raise SystemExit(f"missing data: {_DATA}\nRun scripts/download_backtest_data.py first.")
    df = pd.read_parquet(_DATA)
    df = df.sort_values("open_time").reset_index(drop=True)
    return df


def _run_combo(
    bars: pd.DataFrame,
    oversold: float,
    sl: float,
    tp: float,
    capital: float,
    mask_before: int = 0,
) -> BracketResult:
    params = TrendPullbackParams(oversold_level=oversold, use_4h_confirmation=_USE_4H)
    sig = compute_trend_pullback_signals(bars, params)
    entries = sig.entries
    if mask_before > 0:
        # Suppress entries during the warm-up prefix so the OOS equity segment
        # starts flat at `capital` (no discontinuity when segments are stitched).
        entries = entries.copy()
        entries.iloc[:mask_before] = False
    cfg = BracketConfig(sl_atr_mult=sl, tp_atr_mult=tp, initial_capital=capital)
    return run_bracket_backtest(bars, entries, sig.atr_series, sig.trend_active, cfg)


def _optimise(train: pd.DataFrame) -> dict[str, float]:
    """Grid-search on the train window; pick best in-sample Sharpe with enough trades."""
    best_score = float("-inf")
    best: dict[str, float] = {
        "oversold_level": 35.0,
        "sl_atr_mult": 1.5,
        "tp_atr_mult": 3.0,
    }
    for oversold, sl, tp in itertools.product(
        _PARAM_GRID["oversold_level"],
        _PARAM_GRID["sl_atr_mult"],
        _PARAM_GRID["tp_atr_mult"],
    ):
        res = _run_combo(train, oversold, sl, tp, 10_000.0)
        m = res.metrics
        if m.total_trades < _MIN_TRAIN_TRADES:
            continue
        score = m.sharpe_ratio
        if score > best_score:
            best_score = score
            best = {"oversold_level": oversold, "sl_atr_mult": sl, "tp_atr_mult": tp}
    return best


def main() -> None:
    global _USE_4H
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--h4", action="store_true", help="require 4h structure confirmation (§4)")
    args = parser.parse_args()
    _USE_4H = args.h4

    bars = _load_bars()
    n = len(bars)
    print(f"loaded {n:,} bars  {bars['open_time'].iloc[0]} → {bars['open_time'].iloc[-1]}")
    print(f"4h confirmation: {'ON' if _USE_4H else 'off'}")

    oos_equity_parts: list[pd.Series] = []
    all_trades = []
    window_log: list[str] = []
    capital = 10_000.0

    start = _WARMUP_BARS
    window_idx = 0
    first_test_start: int | None = None
    last_test_end: int | None = None

    while start + _TRAIN_BARS + _TEST_BARS <= n:
        train_lo = start - _WARMUP_BARS  # include warm-up so indicators are valid
        train = bars.iloc[train_lo : start + _TRAIN_BARS].reset_index(drop=True)
        test_lo = start + _TRAIN_BARS - _WARMUP_BARS  # warm-up before the test span
        test = bars.iloc[test_lo : start + _TRAIN_BARS + _TEST_BARS].reset_index(drop=True)

        best = _optimise(train)
        res = _run_combo(
            test,
            best["oversold_level"],
            best["sl_atr_mult"],
            best["tp_atr_mult"],
            capital,
            mask_before=_WARMUP_BARS,
        )
        # Only keep the OOS test span (drop the warm-up prefix from the equity curve).
        oos_curve = res.equity_curve.iloc[_WARMUP_BARS:]
        if not oos_curve.empty:
            capital = float(oos_curve.iloc[-1])
            oos_equity_parts.append(oos_curve)
        # Keep only trades that entered in the OOS span.
        oos_start_ts = pd.Timestamp(bars["open_time"].iloc[start + _TRAIN_BARS])
        oos_window_trades = [t for t in res.trades if t.entry_time >= oos_start_ts]
        all_trades.extend(oos_window_trades)

        if first_test_start is None:
            first_test_start = start + _TRAIN_BARS
        last_test_end = start + _TRAIN_BARS + _TEST_BARS

        window_log.append(
            f"  win {window_idx}: train[{train_lo}:{start + _TRAIN_BARS}] "
            f"test[{test_lo + _WARMUP_BARS}:{start + _TRAIN_BARS + _TEST_BARS}]  "
            f"params={best}  oos_trades={len(oos_window_trades)}"
        )
        window_idx += 1
        start += _TEST_BARS

    if not oos_equity_parts:
        raise SystemExit("no OOS windows produced — check data size / window params")

    oos_equity = pd.concat(oos_equity_parts)
    oos_equity = oos_equity[~oos_equity.index.duplicated(keep="last")]

    # Buy-and-hold over the exact OOS span.
    assert first_test_start is not None and last_test_end is not None
    bh_bars = bars.iloc[first_test_start:last_test_end].reset_index(drop=True)
    bh_equity = buy_and_hold_equity(bh_bars, initial_capital=10_000.0)

    # Resample equity to DAILY before computing return-based metrics. A strategy
    # that is flat most of the time produces a misleadingly high per-bar Sharpe
    # (the std is diluted by zero-return bars). Daily resampling is the honest,
    # standard basis; max-drawdown is frequency-invariant either way.
    strat_daily = oos_equity.resample("1D").last().ffill()
    bh_daily = bh_equity.resample("1D").last().ffill()

    strat_returns = [t.net_return_pct for t in all_trades]
    strat_metrics = compute_metrics(
        strat_daily,
        strat_returns,
        pd.Series(True, index=strat_daily.index),
        annual_trading_days=365,
    )
    bh_metrics = compute_metrics(
        bh_daily, [], pd.Series(True, index=bh_daily.index), annual_trading_days=365
    )

    reason_counts: dict[str, int] = {}
    for t in all_trades:
        reason_counts[t.exit_reason] = reason_counts.get(t.exit_reason, 0) + 1

    print("\n── walk-forward windows ──")
    for line in window_log:
        print(line)

    print("\n── OUT-OF-SAMPLE RESULT (stitched) ──")
    print(f"OOS span: {oos_equity.index[0]} → {oos_equity.index[-1]}  ({len(oos_equity):,} bars)")
    print(f"{'metric':<22}{'Trend Pullback':>18}{'Buy & Hold':>18}")
    rows = [
        ("Total return %", strat_metrics.total_return_pct, bh_metrics.total_return_pct),
        ("CAGR %", strat_metrics.cagr_pct, bh_metrics.cagr_pct),
        ("Sharpe", strat_metrics.sharpe_ratio, bh_metrics.sharpe_ratio),
        ("Sortino", strat_metrics.sortino_ratio, bh_metrics.sortino_ratio),
        ("Calmar", strat_metrics.calmar_ratio, bh_metrics.calmar_ratio),
        ("Max drawdown %", strat_metrics.max_drawdown_pct, bh_metrics.max_drawdown_pct),
        ("Win rate %", strat_metrics.win_rate, bh_metrics.win_rate),
        ("Total trades", float(strat_metrics.total_trades), float(bh_metrics.total_trades)),
    ]
    for name, a, b in rows:
        print(f"{name:<22}{a:>18.2f}{b:>18.2f}")

    print("\n── exit-reason distribution ──")
    total = sum(reason_counts.values()) or 1
    for reason, cnt in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<16}{cnt:>5}  ({cnt / total:.0%})")

    # Honest verdict.
    print("\n── VERDICT ──")
    beats_return = strat_metrics.total_return_pct > bh_metrics.total_return_pct
    beats_sharpe = strat_metrics.sharpe_ratio > bh_metrics.sharpe_ratio
    lower_dd = abs(strat_metrics.max_drawdown_pct) < abs(bh_metrics.max_drawdown_pct)
    print(f"  beats buy-and-hold on total return:  {'YES' if beats_return else 'no'}")
    print(f"  beats buy-and-hold on Sharpe:        {'YES' if beats_sharpe else 'no'}")
    print(f"  lower max drawdown than buy-and-hold: {'YES' if lower_dd else 'no'}")
    if beats_sharpe and lower_dd:
        print("  → risk-adjusted EDGE present (better Sharpe + lower DD).")
    elif beats_return:
        print("  → beats on raw return; check whether it's just more risk.")
    else:
        print("  → NO demonstrated edge over buy-and-hold on this data.")


if __name__ == "__main__":
    main()
