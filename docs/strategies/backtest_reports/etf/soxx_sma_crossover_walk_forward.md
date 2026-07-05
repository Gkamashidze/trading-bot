# Walk-Forward Backtest — soxx_sma_crossover on SOXX

_Generated: 2026-07-05 19:06 UTC · Out-of-sample span: 2003-07-21 04:00 → 2026-07-02 04:00 · 45 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +59.6% vs buy-and-hold +4360.1% (-4300.5 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +59.61 | +4360.11 |
| CAGR % | +2.06 | +18.02 |
| Sharpe | 0.20 | 0.69 |
| Sortino | 0.22 | 0.98 |
| Max drawdown % | -57.17 | -66.85 |
| Calmar | 0.04 | 0.27 |
| Win rate % | 46.6 | 100.0 |
| Profit factor | 2.06 | — |
| Trades | 73 | 1 |
| Exposure % | 63.3 | 100.0 |
| Fees paid ($) | 1143.33 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 2003-07-21 04:00 → 2004-01-16 05:00 | fast=10, slow=50 | 0.39 |
| 1 | 2004-01-20 05:00 → 2004-07-20 04:00 | fast=10, slow=50 | 0.00 |
| 2 | 2004-07-21 04:00 → 2005-01-18 05:00 | fast=10, slow=50 | 0.52 |
| 3 | 2005-01-19 05:00 → 2005-07-19 04:00 | fast=10, slow=50 | 0.00 |
| 4 | 2005-07-20 04:00 → 2006-01-18 05:00 | fast=20, slow=50 | 0.04 |
| 5 | 2006-01-19 05:00 → 2006-07-19 04:00 | fast=20, slow=50 | 0.19 |
| 6 | 2006-07-20 04:00 → 2007-01-19 05:00 | fast=20, slow=50 | -0.23 |
| 7 | 2007-01-22 05:00 → 2007-07-20 04:00 | fast=10, slow=50 | 0.16 |
| 8 | 2007-07-23 04:00 → 2008-01-18 05:00 | fast=10, slow=50 | 0.27 |
| 9 | 2008-01-22 05:00 → 2008-07-21 04:00 | fast=10, slow=100 | -0.05 |
| 10 | 2008-07-22 04:00 → 2009-01-20 05:00 | fast=10, slow=50 | -0.09 |
| 11 | 2009-01-21 05:00 → 2009-07-21 04:00 | fast=10, slow=50 | -0.85 |
| 12 | 2009-07-22 04:00 → 2010-01-20 05:00 | fast=10, slow=50 | 0.08 |
| 13 | 2010-01-21 05:00 → 2010-07-21 04:00 | fast=10, slow=50 | 0.31 |
| 14 | 2010-07-22 04:00 → 2011-01-19 05:00 | fast=10, slow=50 | 0.36 |
| 15 | 2011-01-20 05:00 → 2011-07-20 04:00 | fast=10, slow=50 | 0.00 |
| 16 | 2011-07-21 04:00 → 2012-01-19 05:00 | fast=10, slow=50 | 0.20 |
| 17 | 2012-01-20 05:00 → 2012-07-19 04:00 | fast=20, slow=50 | 0.74 |
| 18 | 2012-07-20 04:00 → 2013-01-22 05:00 | fast=10, slow=100 | -0.28 |
| 19 | 2013-01-23 05:00 → 2013-07-23 04:00 | fast=20, slow=50 | 0.43 |
| 20 | 2013-07-24 04:00 → 2014-01-22 05:00 | fast=20, slow=50 | 0.76 |
| 21 | 2014-01-23 05:00 → 2014-07-23 04:00 | fast=10, slow=50 | 0.00 |
| 22 | 2014-07-24 04:00 → 2015-01-22 05:00 | fast=10, slow=50 | 1.54 |
| 23 | 2015-01-23 05:00 → 2015-07-23 04:00 | fast=10, slow=50 | 0.72 |
| 24 | 2015-07-24 04:00 → 2016-01-22 05:00 | fast=10, slow=50 | -0.30 |
| 25 | 2016-01-25 05:00 → 2016-07-22 04:00 | fast=10, slow=50 | -0.32 |
| 26 | 2016-07-25 04:00 → 2017-01-23 05:00 | fast=10, slow=50 | 0.04 |
| 27 | 2017-01-24 05:00 → 2017-07-24 04:00 | fast=10, slow=50 | 0.78 |
| 28 | 2017-07-25 04:00 → 2018-01-23 05:00 | fast=10, slow=50 | 1.12 |
| 29 | 2018-01-24 05:00 → 2018-07-24 04:00 | fast=10, slow=50 | 1.63 |
| 30 | 2018-07-25 04:00 → 2019-01-24 05:00 | fast=10, slow=50 | -0.09 |
| 31 | 2019-01-25 05:00 → 2019-07-25 04:00 | fast=20, slow=50 | 0.53 |
| 32 | 2019-07-26 04:00 → 2020-01-24 05:00 | fast=20, slow=50 | 0.51 |
| 33 | 2020-01-27 05:00 → 2020-07-24 04:00 | fast=20, slow=50 | 0.78 |
| 34 | 2020-07-27 04:00 → 2021-01-25 05:00 | fast=10, slow=50 | 0.83 |
| 35 | 2021-01-26 05:00 → 2021-07-26 04:00 | fast=10, slow=50 | 1.26 |
| 36 | 2021-07-27 04:00 → 2022-01-24 05:00 | fast=10, slow=50 | 1.09 |
| 37 | 2022-01-25 05:00 → 2022-07-26 04:00 | fast=10, slow=50 | 1.20 |
| 38 | 2022-07-27 04:00 → 2023-01-25 05:00 | fast=10, slow=50 | -0.61 |
| 39 | 2023-01-26 05:00 → 2023-07-27 04:00 | fast=10, slow=50 | -0.60 |
| 40 | 2023-07-28 04:00 → 2024-01-26 05:00 | fast=10, slow=50 | -0.05 |
| 41 | 2024-01-29 05:00 → 2024-07-29 04:00 | fast=10, slow=50 | 0.25 |
| 42 | 2024-07-30 04:00 → 2025-01-29 05:00 | fast=10, slow=50 | 0.63 |
| 43 | 2025-01-30 05:00 → 2025-07-31 04:00 | fast=10, slow=50 | 0.39 |
| 44 | 2025-08-01 04:00 → 2026-01-30 05:00 | fast=10, slow=50 | 0.37 |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
