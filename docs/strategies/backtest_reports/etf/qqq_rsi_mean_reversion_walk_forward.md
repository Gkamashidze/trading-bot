# Walk-Forward Backtest — qqq_rsi_mean_reversion on QQQ

_Generated: 2026-07-05 19:06 UTC · Out-of-sample span: 2001-03-08 05:00 → 2026-07-02 04:00 · 50 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +113.5% vs buy-and-hold +1643.7% (-1530.2 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +113.47 | +1643.67 |
| CAGR % | +3.05 | +11.98 |
| Sharpe | 0.25 | 0.59 |
| Sortino | 0.23 | 0.78 |
| Max drawdown % | -53.69 | -60.71 |
| Calmar | 0.06 | 0.20 |
| Win rate % | 74.4 | 100.0 |
| Profit factor | 1.39 | — |
| Trades | 78 | 1 |
| Exposure % | 41.7 | 100.0 |
| Fees paid ($) | 1736.26 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 2001-03-08 05:00 → 2001-09-05 04:00 | period=7, oversold=35.0, overbought=65.0 | 0.46 |
| 1 | 2001-09-06 04:00 → 2002-03-13 05:00 | period=7, oversold=25.0, overbought=65.0 | 0.02 |
| 2 | 2002-03-14 05:00 → 2002-09-11 04:00 | period=7, oversold=25.0, overbought=70.0 | 0.12 |
| 3 | 2002-09-12 04:00 → 2003-03-13 05:00 | period=7, oversold=25.0, overbought=70.0 | -0.38 |
| 4 | 2003-03-14 05:00 → 2003-09-11 04:00 | period=7, oversold=25.0, overbought=70.0 | 0.14 |
| 5 | 2003-09-12 04:00 → 2004-03-12 05:00 | period=7, oversold=30.0, overbought=70.0 | 0.11 |
| 6 | 2004-03-15 05:00 → 2004-09-13 04:00 | period=7, oversold=35.0, overbought=75.0 | -0.06 |
| 7 | 2004-09-14 04:00 → 2005-03-14 05:00 | period=7, oversold=30.0, overbought=75.0 | 1.08 |
| 8 | 2005-03-15 05:00 → 2005-09-12 04:00 | period=7, oversold=35.0, overbought=70.0 | 0.76 |
| 9 | 2005-09-13 04:00 → 2006-03-14 05:00 | period=7, oversold=25.0, overbought=75.0 | 0.60 |
| 10 | 2006-03-15 05:00 → 2006-09-12 04:00 | period=7, oversold=25.0, overbought=75.0 | 0.78 |
| 11 | 2006-09-13 04:00 → 2007-03-15 04:00 | period=7, oversold=25.0, overbought=75.0 | 0.74 |
| 12 | 2007-03-16 04:00 → 2007-09-13 04:00 | period=7, oversold=30.0, overbought=75.0 | 0.76 |
| 13 | 2007-09-14 04:00 → 2008-03-14 04:00 | period=7, oversold=35.0, overbought=75.0 | 0.96 |
| 14 | 2008-03-17 04:00 → 2008-09-12 04:00 | period=7, oversold=35.0, overbought=65.0 | -0.01 |
| 15 | 2008-09-15 04:00 → 2009-03-16 04:00 | period=7, oversold=35.0, overbought=75.0 | 0.52 |
| 16 | 2009-03-17 04:00 → 2009-09-14 04:00 | period=7, oversold=35.0, overbought=65.0 | -0.41 |
| 17 | 2009-09-15 04:00 → 2010-03-16 04:00 | period=7, oversold=35.0, overbought=75.0 | -0.06 |
| 18 | 2010-03-17 04:00 → 2010-09-14 04:00 | period=7, oversold=35.0, overbought=70.0 | 0.30 |
| 19 | 2010-09-15 04:00 → 2011-03-15 04:00 | period=7, oversold=35.0, overbought=75.0 | 0.45 |
| 20 | 2011-03-16 04:00 → 2011-09-13 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.13 |
| 21 | 2011-09-14 04:00 → 2012-03-14 04:00 | period=7, oversold=25.0, overbought=65.0 | 0.96 |
| 22 | 2012-03-15 04:00 → 2012-09-12 04:00 | period=7, oversold=25.0, overbought=65.0 | 1.36 |
| 23 | 2012-09-13 04:00 → 2013-03-18 04:00 | period=7, oversold=25.0, overbought=70.0 | 1.31 |
| 24 | 2013-03-19 04:00 → 2013-09-16 04:00 | period=7, oversold=25.0, overbought=70.0 | 1.07 |
| 25 | 2013-09-17 04:00 → 2014-03-18 04:00 | period=7, oversold=35.0, overbought=70.0 | 1.27 |
| 26 | 2014-03-19 04:00 → 2014-09-16 04:00 | period=7, oversold=35.0, overbought=70.0 | 1.30 |
| 27 | 2014-09-17 04:00 → 2015-03-18 04:00 | period=7, oversold=35.0, overbought=70.0 | 1.70 |
| 28 | 2015-03-19 04:00 → 2015-09-16 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.96 |
| 29 | 2015-09-17 04:00 → 2016-03-17 04:00 | period=7, oversold=30.0, overbought=75.0 | 1.33 |
| 30 | 2016-03-18 04:00 → 2016-09-15 04:00 | period=7, oversold=30.0, overbought=75.0 | 0.93 |
| 31 | 2016-09-16 04:00 → 2017-03-17 04:00 | period=14, oversold=35.0, overbought=65.0 | 1.19 |
| 32 | 2017-03-20 04:00 → 2017-09-15 04:00 | period=14, oversold=35.0, overbought=65.0 | 1.27 |
| 33 | 2017-09-18 04:00 → 2018-03-19 04:00 | period=14, oversold=35.0, overbought=65.0 | 1.80 |
| 34 | 2018-03-20 04:00 → 2018-09-17 04:00 | period=7, oversold=35.0, overbought=70.0 | 1.90 |
| 35 | 2018-09-18 04:00 → 2019-03-20 04:00 | period=7, oversold=35.0, overbought=70.0 | 1.81 |
| 36 | 2019-03-21 04:00 → 2019-09-18 04:00 | period=7, oversold=35.0, overbought=75.0 | 0.88 |
| 37 | 2019-09-19 04:00 → 2020-03-19 04:00 | period=14, oversold=35.0, overbought=65.0 | 0.91 |
| 38 | 2020-03-20 04:00 → 2020-09-17 04:00 | period=7, oversold=35.0, overbought=75.0 | 0.06 |
| 39 | 2020-09-18 04:00 → 2021-03-19 04:00 | period=7, oversold=25.0, overbought=65.0 | 0.08 |
| 40 | 2021-03-22 04:00 → 2021-09-17 04:00 | period=7, oversold=30.0, overbought=70.0 | 0.56 |
| 41 | 2021-09-20 04:00 → 2022-03-18 04:00 | period=7, oversold=35.0, overbought=70.0 | 0.64 |
| 42 | 2022-03-21 04:00 → 2022-09-19 04:00 | period=7, oversold=30.0, overbought=70.0 | 0.56 |
| 43 | 2022-09-20 04:00 → 2023-03-21 04:00 | period=7, oversold=25.0, overbought=75.0 | 0.24 |
| 44 | 2023-03-22 04:00 → 2023-09-20 04:00 | period=7, oversold=25.0, overbought=75.0 | 0.14 |
| 45 | 2023-09-21 04:00 → 2024-03-21 04:00 | period=7, oversold=25.0, overbought=65.0 | 0.19 |
| 46 | 2024-03-22 04:00 → 2024-09-20 04:00 | period=7, oversold=25.0, overbought=65.0 | 0.94 |
| 47 | 2024-09-23 04:00 → 2025-03-25 04:00 | period=7, oversold=25.0, overbought=65.0 | 1.58 |
| 48 | 2025-03-26 04:00 → 2025-09-24 04:00 | period=7, oversold=25.0, overbought=65.0 | 1.27 |
| 49 | 2025-09-25 04:00 → 2026-03-26 04:00 | period=7, oversold=35.0, overbought=70.0 | 0.87 |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
