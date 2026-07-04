# Walk-Forward Backtest — donchian_breakout on BTC/USDT

_Generated: 2026-07-04 21:09 UTC · Out-of-sample span: 2022-06-30 00:00 → 2026-06-30 23:00 · 48 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +39.4% vs buy-and-hold +192.6% (-153.2 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +39.35 | +192.57 |
| CAGR % | +8.64 | +30.74 |
| Sharpe | 0.42 | 0.80 |
| Sortino | 0.37 | 1.02 |
| Max drawdown % | -43.76 | -53.74 |
| Calmar | 0.20 | 0.57 |
| Win rate % | 35.7 | 100.0 |
| Profit factor | 1.45 | — |
| Trades | 28 | 1 |
| Exposure % | 47.0 | 100.0 |
| Fees paid ($) | 608.05 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 2022-06-30 00:00 → 2022-07-29 23:00 | entry=480, exit_period=240 | 0.00 |
| 1 | 2022-07-30 00:00 → 2022-08-28 23:00 | entry=480, exit_period=240 | 0.00 |
| 2 | 2022-08-29 00:00 → 2022-09-27 23:00 | entry=480, exit_period=240 | -1.02 |
| 3 | 2022-09-28 00:00 → 2022-10-27 23:00 | entry=480, exit_period=240 | -2.09 |
| 4 | 2022-10-28 00:00 → 2022-11-26 23:00 | entry=480, exit_period=480 | -0.98 |
| 5 | 2022-11-27 00:00 → 2022-12-26 23:00 | entry=480, exit_period=480 | -1.34 |
| 6 | 2022-12-27 00:00 → 2023-01-25 23:00 | entry=480, exit_period=480 | -2.50 |
| 7 | 2023-01-26 00:00 → 2023-02-24 23:00 | entry=480, exit_period=240 | 0.36 |
| 8 | 2023-02-25 00:00 → 2023-03-27 00:00 | entry=480, exit_period=480 | 1.09 |
| 9 | 2023-03-27 01:00 → 2023-04-26 00:00 | entry=960, exit_period=240 | 1.14 |
| 10 | 2023-04-26 01:00 → 2023-05-26 00:00 | entry=480, exit_period=480 | 1.26 |
| 11 | 2023-05-26 01:00 → 2023-06-25 00:00 | entry=480, exit_period=240 | 1.62 |
| 12 | 2023-06-25 01:00 → 2023-07-25 00:00 | entry=480, exit_period=480 | 0.81 |
| 13 | 2023-07-25 01:00 → 2023-08-24 00:00 | entry=480, exit_period=240 | 0.34 |
| 14 | 2023-08-24 01:00 → 2023-09-23 00:00 | entry=480, exit_period=240 | 0.00 |
| 15 | 2023-09-23 01:00 → 2023-10-23 00:00 | entry=480, exit_period=240 | 0.00 |
| 16 | 2023-10-23 01:00 → 2023-11-22 00:00 | entry=480, exit_period=240 | 0.00 |
| 17 | 2023-11-22 01:00 → 2023-12-22 00:00 | entry=480, exit_period=240 | 1.66 |
| 18 | 2023-12-22 01:00 → 2024-01-21 00:00 | entry=480, exit_period=240 | 0.00 |
| 19 | 2024-01-21 01:00 → 2024-02-20 00:00 | entry=480, exit_period=240 | 0.00 |
| 20 | 2024-02-20 01:00 → 2024-03-21 00:00 | entry=480, exit_period=240 | 2.42 |
| 21 | 2024-03-21 01:00 → 2024-04-20 00:00 | entry=480, exit_period=240 | 0.00 |
| 22 | 2024-04-20 01:00 → 2024-05-20 00:00 | entry=480, exit_period=240 | 1.81 |
| 23 | 2024-05-20 01:00 → 2024-06-19 00:00 | entry=480, exit_period=480 | 1.18 |
| 24 | 2024-06-19 01:00 → 2024-07-19 00:00 | entry=480, exit_period=480 | 0.75 |
| 25 | 2024-07-19 01:00 → 2024-08-18 00:00 | entry=480, exit_period=240 | 1.51 |
| 26 | 2024-08-18 01:00 → 2024-09-17 00:00 | entry=480, exit_period=480 | -1.15 |
| 27 | 2024-09-17 01:00 → 2024-10-17 00:00 | entry=480, exit_period=240 | -0.94 |
| 28 | 2024-10-17 01:00 → 2024-11-16 00:00 | entry=480, exit_period=240 | -0.99 |
| 29 | 2024-11-16 01:00 → 2024-12-16 00:00 | entry=960, exit_period=240 | 1.28 |
| 30 | 2024-12-16 01:00 → 2025-01-15 00:00 | entry=960, exit_period=240 | 1.97 |
| 31 | 2025-01-15 01:00 → 2025-02-14 00:00 | entry=480, exit_period=240 | 1.29 |
| 32 | 2025-02-14 01:00 → 2025-03-16 00:00 | entry=480, exit_period=240 | 1.44 |
| 33 | 2025-03-16 01:00 → 2025-04-15 00:00 | entry=480, exit_period=240 | 0.00 |
| 34 | 2025-04-15 01:00 → 2025-05-15 00:00 | entry=480, exit_period=240 | 0.00 |
| 35 | 2025-05-15 01:00 → 2025-06-14 00:00 | entry=480, exit_period=240 | 0.06 |
| 36 | 2025-06-14 01:00 → 2025-07-14 00:00 | entry=480, exit_period=240 | 0.00 |
| 37 | 2025-07-14 01:00 → 2025-08-13 00:00 | entry=480, exit_period=240 | 0.00 |
| 38 | 2025-08-13 01:00 → 2025-09-12 00:00 | entry=480, exit_period=240 | 1.85 |
| 39 | 2025-09-12 01:00 → 2025-10-12 00:00 | entry=480, exit_period=240 | 1.45 |
| 40 | 2025-10-12 01:00 → 2025-11-11 00:00 | entry=480, exit_period=240 | -0.56 |
| 41 | 2025-11-11 01:00 → 2025-12-11 00:00 | entry=480, exit_period=240 | -1.09 |
| 42 | 2025-12-11 01:00 → 2026-01-10 00:00 | entry=480, exit_period=240 | -1.65 |
| 43 | 2026-01-10 01:00 → 2026-02-09 00:00 | entry=480, exit_period=240 | -2.59 |
| 44 | 2026-02-09 01:00 → 2026-03-11 00:00 | entry=480, exit_period=480 | -2.09 |
| 45 | 2026-03-11 01:00 → 2026-04-10 00:00 | entry=480, exit_period=480 | -1.72 |
| 46 | 2026-04-10 01:00 → 2026-05-10 00:00 | entry=480, exit_period=240 | -1.49 |
| 47 | 2026-05-10 01:00 → 2026-06-09 00:00 | entry=480, exit_period=240 | -0.38 |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
