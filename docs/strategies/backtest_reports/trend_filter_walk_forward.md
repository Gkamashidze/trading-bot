# Walk-Forward Backtest — trend_filter on BTC/USDT

_Generated: 2026-07-04 21:09 UTC · Out-of-sample span: 2022-06-30 00:00 → 2026-06-30 23:00 · 48 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +82.1% vs buy-and-hold +192.6% (-110.5 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +82.08 | +192.57 |
| CAGR % | +16.14 | +30.74 |
| Sharpe | 0.62 | 0.80 |
| Sortino | 0.61 | 1.02 |
| Max drawdown % | -37.83 | -53.74 |
| Calmar | 0.43 | 0.57 |
| Win rate % | 12.6 | 100.0 |
| Profit factor | 1.65 | — |
| Trades | 223 | 1 |
| Exposure % | 59.1 | 100.0 |
| Fees paid ($) | 7125.14 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 2022-06-30 00:00 → 2022-07-29 23:00 | period=480 | -0.53 |
| 1 | 2022-07-30 00:00 → 2022-08-28 23:00 | period=480 | -0.31 |
| 2 | 2022-08-29 00:00 → 2022-09-27 23:00 | period=480 | -0.34 |
| 3 | 2022-09-28 00:00 → 2022-10-27 23:00 | period=480 | -0.74 |
| 4 | 2022-10-28 00:00 → 2022-11-26 23:00 | period=480 | -1.16 |
| 5 | 2022-11-27 00:00 → 2022-12-26 23:00 | period=480 | -0.93 |
| 6 | 2022-12-27 00:00 → 2023-01-25 23:00 | period=480 | -1.53 |
| 7 | 2023-01-26 00:00 → 2023-02-24 23:00 | period=2400 | 2.52 |
| 8 | 2023-02-25 00:00 → 2023-03-27 00:00 | period=1200 | 1.57 |
| 9 | 2023-03-27 01:00 → 2023-04-26 00:00 | period=1200 | 2.63 |
| 10 | 2023-04-26 01:00 → 2023-05-26 00:00 | period=1200 | 2.55 |
| 11 | 2023-05-26 01:00 → 2023-06-25 00:00 | period=480 | 1.27 |
| 12 | 2023-06-25 01:00 → 2023-07-25 00:00 | period=1200 | 1.60 |
| 13 | 2023-07-25 01:00 → 2023-08-24 00:00 | period=1200 | 1.11 |
| 14 | 2023-08-24 01:00 → 2023-09-23 00:00 | period=2400 | 0.10 |
| 15 | 2023-09-23 01:00 → 2023-10-23 00:00 | period=1200 | -0.70 |
| 16 | 2023-10-23 01:00 → 2023-11-22 00:00 | period=1200 | 0.72 |
| 17 | 2023-11-22 01:00 → 2023-12-22 00:00 | period=2400 | 2.35 |
| 18 | 2023-12-22 01:00 → 2024-01-21 00:00 | period=2400 | 3.54 |
| 19 | 2024-01-21 01:00 → 2024-02-20 00:00 | period=1200 | 2.33 |
| 20 | 2024-02-20 01:00 → 2024-03-21 00:00 | period=480 | 2.97 |
| 21 | 2024-03-21 01:00 → 2024-04-20 00:00 | period=480 | 3.43 |
| 22 | 2024-04-20 01:00 → 2024-05-20 00:00 | period=480 | 1.61 |
| 23 | 2024-05-20 01:00 → 2024-06-19 00:00 | period=480 | 1.13 |
| 24 | 2024-06-19 01:00 → 2024-07-19 00:00 | period=1200 | 1.62 |
| 25 | 2024-07-19 01:00 → 2024-08-18 00:00 | period=480 | 1.33 |
| 26 | 2024-08-18 01:00 → 2024-09-17 00:00 | period=480 | -0.88 |
| 27 | 2024-09-17 01:00 → 2024-10-17 00:00 | period=480 | -0.44 |
| 28 | 2024-10-17 01:00 → 2024-11-16 00:00 | period=480 | 0.69 |
| 29 | 2024-11-16 01:00 → 2024-12-16 00:00 | period=2400 | 2.64 |
| 30 | 2024-12-16 01:00 → 2025-01-15 00:00 | period=2400 | 2.74 |
| 31 | 2025-01-15 01:00 → 2025-02-14 00:00 | period=1200 | 1.65 |
| 32 | 2025-02-14 01:00 → 2025-03-16 00:00 | period=480 | 1.28 |
| 33 | 2025-03-16 01:00 → 2025-04-15 00:00 | period=1200 | 0.81 |
| 34 | 2025-04-15 01:00 → 2025-05-15 00:00 | period=480 | 0.24 |
| 35 | 2025-05-15 01:00 → 2025-06-14 00:00 | period=3600 | 1.05 |
| 36 | 2025-06-14 01:00 → 2025-07-14 00:00 | period=1200 | 0.18 |
| 37 | 2025-07-14 01:00 → 2025-08-13 00:00 | period=1200 | 1.24 |
| 38 | 2025-08-13 01:00 → 2025-09-12 00:00 | period=1200 | 1.16 |
| 39 | 2025-09-12 01:00 → 2025-10-12 00:00 | period=1200 | 0.89 |
| 40 | 2025-10-12 01:00 → 2025-11-11 00:00 | period=1200 | -0.41 |
| 41 | 2025-11-11 01:00 → 2025-12-11 00:00 | period=1200 | -0.42 |
| 42 | 2025-12-11 01:00 → 2026-01-10 00:00 | period=1200 | -1.06 |
| 43 | 2026-01-10 01:00 → 2026-02-09 00:00 | period=1200 | -1.16 |
| 44 | 2026-02-09 01:00 → 2026-03-11 00:00 | period=1200 | -1.64 |
| 45 | 2026-03-11 01:00 → 2026-04-10 00:00 | period=1200 | -0.88 |
| 46 | 2026-04-10 01:00 → 2026-05-10 00:00 | period=480 | -2.24 |
| 47 | 2026-05-10 01:00 → 2026-06-09 00:00 | period=2400 | 0.22 |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
