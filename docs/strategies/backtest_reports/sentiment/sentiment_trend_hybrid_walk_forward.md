# Walk-Forward Backtest — sentiment_trend_hybrid on BTC/USDT

_Generated: 2026-07-05 19:15 UTC · Out-of-sample span: 2019-05-20 00:00 → 2026-06-30 00:00 · 20 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +592.5% vs buy-and-hold +638.5% (-46.0 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +592.51 | +638.52 |
| CAGR % | +31.23 | +32.42 |
| Sharpe | 0.89 | 0.77 |
| Sortino | 0.95 | 1.04 |
| Max drawdown % | -56.18 | -76.63 |
| Calmar | 0.56 | 0.42 |
| Win rate % | 24.1 | 100.0 |
| Profit factor | 3.50 | — |
| Trades | 58 | 1 |
| Exposure % | 48.2 | 100.0 |
| Fees paid ($) | 7274.82 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 2019-05-20 00:00 → 2019-09-22 00:00 | funding_below=-0.0001, exit_ma=20 | -0.05 |
| 1 | 2019-09-23 00:00 → 2020-01-26 00:00 | funding_below=-0.0001, exit_ma=20 | 0.00 |
| 2 | 2020-01-27 00:00 → 2020-05-31 00:00 | funding_below=0.0001, exit_ma=100 | 0.05 |
| 3 | 2020-06-01 00:00 → 2020-10-04 00:00 | funding_below=0.0001, exit_ma=50 | 0.99 |
| 4 | 2020-10-05 00:00 → 2021-02-07 00:00 | funding_below=0.0001, exit_ma=50 | 0.82 |
| 5 | 2021-02-08 00:00 → 2021-06-13 00:00 | funding_below=0.0001, exit_ma=50 | 2.60 |
| 6 | 2021-06-14 00:00 → 2021-10-17 00:00 | funding_below=0.0001, exit_ma=50 | 2.65 |
| 7 | 2021-10-18 00:00 → 2022-02-20 00:00 | funding_below=0.0001, exit_ma=50 | 2.80 |
| 8 | 2022-02-21 00:00 → 2022-06-26 00:00 | funding_below=0.0001, exit_ma=50 | 2.06 |
| 9 | 2022-06-27 00:00 → 2022-10-30 00:00 | funding_below=0.0, exit_ma=50 | 0.45 |
| 10 | 2022-10-31 00:00 → 2023-03-05 00:00 | funding_below=0.0, exit_ma=20 | -0.03 |
| 11 | 2023-03-06 00:00 → 2023-07-09 00:00 | funding_below=0.0001, exit_ma=100 | 0.07 |
| 12 | 2023-07-10 00:00 → 2023-11-12 00:00 | funding_below=0.0001, exit_ma=100 | 0.60 |
| 13 | 2023-11-13 00:00 → 2024-03-17 00:00 | funding_below=0.0, exit_ma=200 | 1.53 |
| 14 | 2024-03-18 00:00 → 2024-07-21 00:00 | funding_below=0.0001, exit_ma=50 | 2.63 |
| 15 | 2024-07-22 00:00 → 2024-11-24 00:00 | funding_below=0.0001, exit_ma=50 | 1.83 |
| 16 | 2024-11-25 00:00 → 2025-03-30 00:00 | funding_below=0.0001, exit_ma=20 | 2.20 |
| 17 | 2025-03-31 00:00 → 2025-08-03 00:00 | funding_below=0.0001, exit_ma=20 | 1.30 |
| 18 | 2025-08-04 00:00 → 2025-12-07 00:00 | funding_below=0.0001, exit_ma=100 | 1.18 |
| 19 | 2025-12-08 00:00 → 2026-04-12 00:00 | funding_below=0.0001, exit_ma=50 | 1.17 |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
