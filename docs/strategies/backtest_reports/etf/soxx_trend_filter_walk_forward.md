# Walk-Forward Backtest — soxx_trend_filter on SOXX

_Generated: 2026-07-05 19:06 UTC · Out-of-sample span: 2003-07-21 04:00 → 2026-07-02 04:00 · 45 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +1193.2% vs buy-and-hold +4360.1% (-3166.9 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +1193.18 | +4360.11 |
| CAGR % | +11.82 | +18.02 |
| Sharpe | 0.62 | 0.69 |
| Sortino | 0.72 | 0.98 |
| Max drawdown % | -38.86 | -66.85 |
| Calmar | 0.30 | 0.27 |
| Win rate % | 32.9 | 100.0 |
| Profit factor | 2.32 | — |
| Trades | 149 | 1 |
| Exposure % | 67.3 | 100.0 |
| Fees paid ($) | 8247.16 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 2003-07-21 04:00 → 2004-01-16 05:00 | period=200 | 0.74 |
| 1 | 2004-01-20 05:00 → 2004-07-20 04:00 | period=100 | 0.89 |
| 2 | 2004-07-21 04:00 → 2005-01-18 05:00 | period=200 | 0.85 |
| 3 | 2005-01-19 05:00 → 2005-07-19 04:00 | period=100 | 0.64 |
| 4 | 2005-07-20 04:00 → 2006-01-18 05:00 | period=20 | 0.67 |
| 5 | 2006-01-19 05:00 → 2006-07-19 04:00 | period=100 | 0.73 |
| 6 | 2006-07-20 04:00 → 2007-01-19 05:00 | period=20 | 0.36 |
| 7 | 2007-01-22 05:00 → 2007-07-20 04:00 | period=50 | 0.19 |
| 8 | 2007-07-23 04:00 → 2008-01-18 05:00 | period=20 | -0.16 |
| 9 | 2008-01-22 05:00 → 2008-07-21 04:00 | period=200 | -0.17 |
| 10 | 2008-07-22 04:00 → 2009-01-20 05:00 | period=200 | -0.62 |
| 11 | 2009-01-21 05:00 → 2009-07-21 04:00 | period=100 | -0.55 |
| 12 | 2009-07-22 04:00 → 2010-01-20 05:00 | period=100 | 0.72 |
| 13 | 2010-01-21 05:00 → 2010-07-21 04:00 | period=100 | 0.93 |
| 14 | 2010-07-22 04:00 → 2011-01-19 05:00 | period=100 | 0.71 |
| 15 | 2011-01-20 05:00 → 2011-07-20 04:00 | period=20 | 1.10 |
| 16 | 2011-07-21 04:00 → 2012-01-19 05:00 | period=150 | 0.39 |
| 17 | 2012-01-20 05:00 → 2012-07-19 04:00 | period=100 | 0.41 |
| 18 | 2012-07-20 04:00 → 2013-01-22 05:00 | period=50 | 0.24 |
| 19 | 2013-01-23 05:00 → 2013-07-23 04:00 | period=50 | -0.07 |
| 20 | 2013-07-24 04:00 → 2014-01-22 05:00 | period=50 | 0.79 |
| 21 | 2014-01-23 05:00 → 2014-07-23 04:00 | period=200 | 1.24 |
| 22 | 2014-07-24 04:00 → 2015-01-22 05:00 | period=100 | 1.47 |
| 23 | 2015-01-23 05:00 → 2015-07-23 04:00 | period=150 | 1.37 |
| 24 | 2015-07-24 04:00 → 2016-01-22 05:00 | period=100 | 0.74 |
| 25 | 2016-01-25 05:00 → 2016-07-22 04:00 | period=200 | -0.23 |
| 26 | 2016-07-25 04:00 → 2017-01-23 05:00 | period=100 | 0.04 |
| 27 | 2017-01-24 05:00 → 2017-07-24 04:00 | period=200 | 1.03 |
| 28 | 2017-07-25 04:00 → 2018-01-23 05:00 | period=150 | 1.82 |
| 29 | 2018-01-24 05:00 → 2018-07-24 04:00 | period=20 | 1.82 |
| 30 | 2018-07-25 04:00 → 2019-01-24 05:00 | period=150 | 0.82 |
| 31 | 2019-01-25 05:00 → 2019-07-25 04:00 | period=150 | 0.55 |
| 32 | 2019-07-26 04:00 → 2020-01-24 05:00 | period=20 | 0.61 |
| 33 | 2020-01-27 05:00 → 2020-07-24 04:00 | period=200 | 1.21 |
| 34 | 2020-07-27 04:00 → 2021-01-25 05:00 | period=50 | 0.75 |
| 35 | 2021-01-26 05:00 → 2021-07-26 04:00 | period=100 | 1.46 |
| 36 | 2021-07-27 04:00 → 2022-01-24 05:00 | period=150 | 1.01 |
| 37 | 2022-01-25 05:00 → 2022-07-26 04:00 | period=100 | 1.00 |
| 38 | 2022-07-27 04:00 → 2023-01-25 05:00 | period=100 | 0.22 |
| 39 | 2023-01-26 05:00 → 2023-07-27 04:00 | period=100 | -0.13 |
| 40 | 2023-07-28 04:00 → 2024-01-26 05:00 | period=150 | 0.47 |
| 41 | 2024-01-29 05:00 → 2024-07-29 04:00 | period=200 | 1.03 |
| 42 | 2024-07-30 04:00 → 2025-01-29 05:00 | period=50 | 1.27 |
| 43 | 2025-01-30 05:00 → 2025-07-31 04:00 | period=50 | 0.54 |
| 44 | 2025-08-01 04:00 → 2026-01-30 05:00 | period=20 | 0.58 |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
