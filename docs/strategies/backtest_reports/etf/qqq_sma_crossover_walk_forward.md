# Walk-Forward Backtest — qqq_sma_crossover on QQQ

_Generated: 2026-07-05 19:06 UTC · Out-of-sample span: 2001-03-08 05:00 → 2026-07-02 04:00 · 50 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +389.2% vs buy-and-hold +1643.7% (-1254.5 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +389.20 | +1643.67 |
| CAGR % | +6.49 | +11.98 |
| Sharpe | 0.50 | 0.59 |
| Sortino | 0.52 | 0.78 |
| Max drawdown % | -35.20 | -60.71 |
| Calmar | 0.18 | 0.20 |
| Win rate % | 52.6 | 100.0 |
| Profit factor | 1.87 | — |
| Trades | 76 | 1 |
| Exposure % | 67.2 | 100.0 |
| Fees paid ($) | 2819.49 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 2001-03-08 05:00 → 2001-09-05 04:00 | fast=10, slow=50 | 0.51 |
| 1 | 2001-09-06 04:00 → 2002-03-13 05:00 | fast=10, slow=50 | 0.00 |
| 2 | 2002-03-14 05:00 → 2002-09-11 04:00 | fast=10, slow=50 | -0.34 |
| 3 | 2002-09-12 04:00 → 2003-03-13 05:00 | fast=20, slow=50 | -0.19 |
| 4 | 2003-03-14 05:00 → 2003-09-11 04:00 | fast=10, slow=50 | -0.51 |
| 5 | 2003-09-12 04:00 → 2004-03-12 05:00 | fast=10, slow=50 | -0.07 |
| 6 | 2004-03-15 05:00 → 2004-09-13 04:00 | fast=10, slow=50 | 0.17 |
| 7 | 2004-09-14 04:00 → 2005-03-14 05:00 | fast=10, slow=50 | 0.13 |
| 8 | 2005-03-15 05:00 → 2005-09-12 04:00 | fast=10, slow=50 | 0.42 |
| 9 | 2005-09-13 04:00 → 2006-03-14 05:00 | fast=10, slow=50 | 0.38 |
| 10 | 2006-03-15 05:00 → 2006-09-12 04:00 | fast=10, slow=50 | 0.52 |
| 11 | 2006-09-13 04:00 → 2007-03-15 04:00 | fast=10, slow=50 | 0.25 |
| 12 | 2007-03-16 04:00 → 2007-09-13 04:00 | fast=10, slow=50 | 0.31 |
| 13 | 2007-09-14 04:00 → 2008-03-14 04:00 | fast=10, slow=50 | 0.49 |
| 14 | 2008-03-17 04:00 → 2008-09-12 04:00 | fast=10, slow=50 | 0.75 |
| 15 | 2008-09-15 04:00 → 2009-03-16 04:00 | fast=10, slow=50 | -0.05 |
| 16 | 2009-03-17 04:00 → 2009-09-14 04:00 | fast=10, slow=50 | -0.63 |
| 17 | 2009-09-15 04:00 → 2010-03-16 04:00 | fast=10, slow=50 | 0.41 |
| 18 | 2010-03-17 04:00 → 2010-09-14 04:00 | fast=10, slow=50 | 0.48 |
| 19 | 2010-09-15 04:00 → 2011-03-15 04:00 | fast=10, slow=50 | 0.59 |
| 20 | 2011-03-16 04:00 → 2011-09-13 04:00 | fast=10, slow=50 | 0.00 |
| 21 | 2011-09-14 04:00 → 2012-03-14 04:00 | fast=10, slow=50 | 0.07 |
| 22 | 2012-03-15 04:00 → 2012-09-12 04:00 | fast=20, slow=50 | 0.39 |
| 23 | 2012-09-13 04:00 → 2013-03-18 04:00 | fast=20, slow=50 | 0.32 |
| 24 | 2013-03-19 04:00 → 2013-09-16 04:00 | fast=20, slow=50 | 0.50 |
| 25 | 2013-09-17 04:00 → 2014-03-18 04:00 | fast=10, slow=50 | 0.97 |
| 26 | 2014-03-19 04:00 → 2014-09-16 04:00 | fast=10, slow=50 | 0.00 |
| 27 | 2014-09-17 04:00 → 2015-03-18 04:00 | fast=10, slow=50 | 0.00 |
| 28 | 2015-03-19 04:00 → 2015-09-16 04:00 | fast=10, slow=50 | 1.25 |
| 29 | 2015-09-17 04:00 → 2016-03-17 04:00 | fast=10, slow=50 | -0.41 |
| 30 | 2016-03-18 04:00 → 2016-09-15 04:00 | fast=10, slow=50 | -0.42 |
| 31 | 2016-09-16 04:00 → 2017-03-17 04:00 | fast=20, slow=50 | -0.29 |
| 32 | 2017-03-20 04:00 → 2017-09-15 04:00 | fast=20, slow=50 | 0.14 |
| 33 | 2017-09-18 04:00 → 2018-03-19 04:00 | fast=20, slow=50 | 1.10 |
| 34 | 2018-03-20 04:00 → 2018-09-17 04:00 | fast=10, slow=50 | 1.28 |
| 35 | 2018-09-18 04:00 → 2019-03-20 04:00 | fast=10, slow=50 | 0.00 |
| 36 | 2019-03-21 04:00 → 2019-09-18 04:00 | fast=10, slow=50 | 0.00 |
| 37 | 2019-09-19 04:00 → 2020-03-19 04:00 | fast=10, slow=100 | 0.24 |
| 38 | 2020-03-20 04:00 → 2020-09-17 04:00 | fast=10, slow=50 | 0.00 |
| 39 | 2020-09-18 04:00 → 2021-03-19 04:00 | fast=10, slow=50 | 1.35 |
| 40 | 2021-03-22 04:00 → 2021-09-17 04:00 | fast=10, slow=50 | 1.01 |
| 41 | 2021-09-20 04:00 → 2022-03-18 04:00 | fast=10, slow=50 | 1.26 |
| 42 | 2022-03-21 04:00 → 2022-09-19 04:00 | fast=10, slow=50 | 0.31 |
| 43 | 2022-09-20 04:00 → 2023-03-21 04:00 | fast=10, slow=50 | -0.25 |
| 44 | 2023-03-22 04:00 → 2023-09-20 04:00 | fast=10, slow=50 | -0.34 |
| 45 | 2023-09-21 04:00 → 2024-03-21 04:00 | fast=10, slow=50 | 0.17 |
| 46 | 2024-03-22 04:00 → 2024-09-20 04:00 | fast=10, slow=50 | 0.87 |
| 47 | 2024-09-23 04:00 → 2025-03-25 04:00 | fast=10, slow=50 | 1.20 |
| 48 | 2025-03-26 04:00 → 2025-09-24 04:00 | fast=10, slow=50 | 0.32 |
| 49 | 2025-09-25 04:00 → 2026-03-26 04:00 | fast=10, slow=50 | 1.00 |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
