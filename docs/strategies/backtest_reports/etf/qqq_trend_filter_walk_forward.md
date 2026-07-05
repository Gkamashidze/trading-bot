# Walk-Forward Backtest — qqq_trend_filter on QQQ

_Generated: 2026-07-05 19:06 UTC · Out-of-sample span: 2001-03-08 05:00 → 2026-07-02 04:00 · 50 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +231.3% vs buy-and-hold +1643.7% (-1412.4 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +231.28 | +1643.67 |
| CAGR % | +4.85 | +11.98 |
| Sharpe | 0.40 | 0.59 |
| Sortino | 0.43 | 0.78 |
| Max drawdown % | -24.92 | -60.71 |
| Calmar | 0.20 | 0.20 |
| Win rate % | 28.4 | 100.0 |
| Profit factor | 2.17 | — |
| Trades | 141 | 1 |
| Exposure % | 74.9 | 100.0 |
| Fees paid ($) | 4722.89 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 2001-03-08 05:00 → 2001-09-05 04:00 | period=50 | 0.51 |
| 1 | 2001-09-06 04:00 → 2002-03-13 05:00 | period=50 | -0.10 |
| 2 | 2002-03-14 05:00 → 2002-09-11 04:00 | period=50 | -0.57 |
| 3 | 2002-09-12 04:00 → 2003-03-13 05:00 | period=100 | -0.58 |
| 4 | 2003-03-14 05:00 → 2003-09-11 04:00 | period=50 | -0.01 |
| 5 | 2003-09-12 04:00 → 2004-03-12 05:00 | period=200 | 0.65 |
| 6 | 2004-03-15 05:00 → 2004-09-13 04:00 | period=200 | 0.85 |
| 7 | 2004-09-14 04:00 → 2005-03-14 05:00 | period=150 | 0.90 |
| 8 | 2005-03-15 05:00 → 2005-09-12 04:00 | period=50 | 0.39 |
| 9 | 2005-09-13 04:00 → 2006-03-14 05:00 | period=50 | 0.12 |
| 10 | 2006-03-15 05:00 → 2006-09-12 04:00 | period=150 | 0.54 |
| 11 | 2006-09-13 04:00 → 2007-03-15 04:00 | period=150 | 0.29 |
| 12 | 2007-03-16 04:00 → 2007-09-13 04:00 | period=200 | 0.09 |
| 13 | 2007-09-14 04:00 → 2008-03-14 04:00 | period=200 | 0.91 |
| 14 | 2008-03-17 04:00 → 2008-09-12 04:00 | period=50 | 0.24 |
| 15 | 2008-09-15 04:00 → 2009-03-16 04:00 | period=200 | -0.18 |
| 16 | 2009-03-17 04:00 → 2009-09-14 04:00 | period=20 | -0.15 |
| 17 | 2009-09-15 04:00 → 2010-03-16 04:00 | period=100 | 0.86 |
| 18 | 2010-03-17 04:00 → 2010-09-14 04:00 | period=100 | 1.22 |
| 19 | 2010-09-15 04:00 → 2011-03-15 04:00 | period=100 | 0.93 |
| 20 | 2011-03-16 04:00 → 2011-09-13 04:00 | period=50 | 1.13 |
| 21 | 2011-09-14 04:00 → 2012-03-14 04:00 | period=100 | 0.62 |
| 22 | 2012-03-15 04:00 → 2012-09-12 04:00 | period=150 | 0.93 |
| 23 | 2012-09-13 04:00 → 2013-03-18 04:00 | period=200 | 0.35 |
| 24 | 2013-03-19 04:00 → 2013-09-16 04:00 | period=200 | 0.54 |
| 25 | 2013-09-17 04:00 → 2014-03-18 04:00 | period=200 | 0.68 |
| 26 | 2014-03-19 04:00 → 2014-09-16 04:00 | period=100 | 1.43 |
| 27 | 2014-09-17 04:00 → 2015-03-18 04:00 | period=100 | 1.38 |
| 28 | 2015-03-19 04:00 → 2015-09-16 04:00 | period=150 | 1.16 |
| 29 | 2015-09-17 04:00 → 2016-03-17 04:00 | period=150 | 0.69 |
| 30 | 2016-03-18 04:00 → 2016-09-15 04:00 | period=150 | 0.42 |
| 31 | 2016-09-16 04:00 → 2017-03-17 04:00 | period=150 | -0.06 |
| 32 | 2017-03-20 04:00 → 2017-09-15 04:00 | period=150 | 0.71 |
| 33 | 2017-09-18 04:00 → 2018-03-19 04:00 | period=150 | 1.30 |
| 34 | 2018-03-20 04:00 → 2018-09-17 04:00 | period=100 | 1.45 |
| 35 | 2018-09-18 04:00 → 2019-03-20 04:00 | period=50 | 1.14 |
| 36 | 2019-03-21 04:00 → 2019-09-18 04:00 | period=50 | 0.84 |
| 37 | 2019-09-19 04:00 → 2020-03-19 04:00 | period=150 | 0.54 |
| 38 | 2020-03-20 04:00 → 2020-09-17 04:00 | period=50 | 0.64 |
| 39 | 2020-09-18 04:00 → 2021-03-19 04:00 | period=50 | 1.15 |
| 40 | 2021-03-22 04:00 → 2021-09-17 04:00 | period=150 | 1.04 |
| 41 | 2021-09-20 04:00 → 2022-03-18 04:00 | period=20 | 1.23 |
| 42 | 2022-03-21 04:00 → 2022-09-19 04:00 | period=20 | 0.81 |
| 43 | 2022-09-20 04:00 → 2023-03-21 04:00 | period=150 | 0.25 |
| 44 | 2023-03-22 04:00 → 2023-09-20 04:00 | period=50 | 0.06 |
| 45 | 2023-09-21 04:00 → 2024-03-21 04:00 | period=200 | 0.97 |
| 46 | 2024-03-22 04:00 → 2024-09-20 04:00 | period=200 | 1.59 |
| 47 | 2024-09-23 04:00 → 2025-03-25 04:00 | period=150 | 1.32 |
| 48 | 2025-03-26 04:00 → 2025-09-24 04:00 | period=20 | 1.06 |
| 49 | 2025-09-25 04:00 → 2026-03-26 04:00 | period=50 | 1.35 |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
