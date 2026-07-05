# Walk-Forward Backtest — soxx_rsi_mean_reversion on SOXX

_Generated: 2026-07-05 19:06 UTC · Out-of-sample span: 2003-07-21 04:00 → 2026-07-02 04:00 · 45 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +603.2% vs buy-and-hold +4360.1% (-3756.9 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +603.22 | +4360.11 |
| CAGR % | +8.88 | +18.02 |
| Sharpe | 0.50 | 0.69 |
| Sortino | 0.48 | 0.98 |
| Max drawdown % | -49.92 | -66.85 |
| Calmar | 0.18 | 0.27 |
| Win rate % | 74.6 | 100.0 |
| Profit factor | 2.38 | — |
| Trades | 71 | 1 |
| Exposure % | 45.0 | 100.0 |
| Fees paid ($) | 4210.65 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 2003-07-21 04:00 → 2004-01-16 05:00 | period=7, oversold=35.0, overbought=75.0 | 0.10 |
| 1 | 2004-01-20 05:00 → 2004-07-20 04:00 | period=7, oversold=35.0, overbought=75.0 | 0.44 |
| 2 | 2004-07-21 04:00 → 2005-01-18 05:00 | period=7, oversold=35.0, overbought=75.0 | 0.75 |
| 3 | 2005-01-19 05:00 → 2005-07-19 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.40 |
| 4 | 2005-07-20 04:00 → 2006-01-18 05:00 | period=7, oversold=25.0, overbought=70.0 | 0.94 |
| 5 | 2006-01-19 05:00 → 2006-07-19 04:00 | period=7, oversold=25.0, overbought=75.0 | 0.59 |
| 6 | 2006-07-20 04:00 → 2007-01-19 05:00 | period=7, oversold=35.0, overbought=75.0 | 0.72 |
| 7 | 2007-01-22 05:00 → 2007-07-20 04:00 | period=7, oversold=35.0, overbought=75.0 | 0.48 |
| 8 | 2007-07-23 04:00 → 2008-01-18 05:00 | period=7, oversold=35.0, overbought=75.0 | 1.10 |
| 9 | 2008-01-22 05:00 → 2008-07-21 04:00 | period=7, oversold=30.0, overbought=65.0 | -0.09 |
| 10 | 2008-07-22 04:00 → 2009-01-20 05:00 | period=7, oversold=30.0, overbought=65.0 | 0.56 |
| 11 | 2009-01-21 05:00 → 2009-07-21 04:00 | period=7, oversold=25.0, overbought=65.0 | -0.18 |
| 12 | 2009-07-22 04:00 → 2010-01-20 05:00 | period=7, oversold=30.0, overbought=75.0 | 0.24 |
| 13 | 2010-01-21 05:00 → 2010-07-21 04:00 | period=7, oversold=30.0, overbought=75.0 | 0.66 |
| 14 | 2010-07-22 04:00 → 2011-01-19 05:00 | period=7, oversold=30.0, overbought=65.0 | 0.65 |
| 15 | 2011-01-20 05:00 → 2011-07-20 04:00 | period=7, oversold=30.0, overbought=65.0 | 1.63 |
| 16 | 2011-07-21 04:00 → 2012-01-19 05:00 | period=7, oversold=25.0, overbought=65.0 | 1.17 |
| 17 | 2012-01-20 05:00 → 2012-07-19 04:00 | period=7, oversold=25.0, overbought=65.0 | 1.69 |
| 18 | 2012-07-20 04:00 → 2013-01-22 05:00 | period=7, oversold=25.0, overbought=70.0 | 1.31 |
| 19 | 2013-01-23 05:00 → 2013-07-23 04:00 | period=7, oversold=25.0, overbought=70.0 | 1.19 |
| 20 | 2013-07-24 04:00 → 2014-01-22 05:00 | period=7, oversold=30.0, overbought=65.0 | 1.47 |
| 21 | 2014-01-23 05:00 → 2014-07-23 04:00 | period=7, oversold=35.0, overbought=70.0 | 1.16 |
| 22 | 2014-07-24 04:00 → 2015-01-22 05:00 | period=7, oversold=35.0, overbought=75.0 | 1.68 |
| 23 | 2015-01-23 05:00 → 2015-07-23 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.69 |
| 24 | 2015-07-24 04:00 → 2016-01-22 05:00 | period=7, oversold=35.0, overbought=75.0 | 1.27 |
| 25 | 2016-01-25 05:00 → 2016-07-22 04:00 | period=14, oversold=35.0, overbought=70.0 | 0.91 |
| 26 | 2016-07-25 04:00 → 2017-01-23 05:00 | period=7, oversold=30.0, overbought=75.0 | 1.18 |
| 27 | 2017-01-24 05:00 → 2017-07-24 04:00 | period=7, oversold=30.0, overbought=75.0 | 1.57 |
| 28 | 2017-07-25 04:00 → 2018-01-23 05:00 | period=7, oversold=30.0, overbought=75.0 | 1.91 |
| 29 | 2018-01-24 05:00 → 2018-07-24 04:00 | period=7, oversold=35.0, overbought=75.0 | 2.87 |
| 30 | 2018-07-25 04:00 → 2019-01-24 05:00 | period=7, oversold=30.0, overbought=75.0 | 1.83 |
| 31 | 2019-01-25 05:00 → 2019-07-25 04:00 | period=7, oversold=25.0, overbought=70.0 | 1.26 |
| 32 | 2019-07-26 04:00 → 2020-01-24 05:00 | period=7, oversold=25.0, overbought=75.0 | 0.96 |
| 33 | 2020-01-27 05:00 → 2020-07-24 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.20 |
| 34 | 2020-07-27 04:00 → 2021-01-25 05:00 | period=7, oversold=35.0, overbought=75.0 | 0.91 |
| 35 | 2021-01-26 05:00 → 2021-07-26 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.14 |
| 36 | 2021-07-27 04:00 → 2022-01-24 05:00 | period=7, oversold=35.0, overbought=75.0 | 1.46 |
| 37 | 2022-01-25 05:00 → 2022-07-26 04:00 | period=7, oversold=25.0, overbought=75.0 | 1.21 |
| 38 | 2022-07-27 04:00 → 2023-01-25 05:00 | period=7, oversold=35.0, overbought=65.0 | 0.93 |
| 39 | 2023-01-26 05:00 → 2023-07-27 04:00 | period=7, oversold=30.0, overbought=70.0 | 0.71 |
| 40 | 2023-07-28 04:00 → 2024-01-26 05:00 | period=7, oversold=25.0, overbought=70.0 | 0.42 |
| 41 | 2024-01-29 05:00 → 2024-07-29 04:00 | period=7, oversold=30.0, overbought=65.0 | 0.80 |
| 42 | 2024-07-30 04:00 → 2025-01-29 05:00 | period=14, oversold=35.0, overbought=70.0 | 1.69 |
| 43 | 2025-01-30 05:00 → 2025-07-31 04:00 | period=7, oversold=25.0, overbought=65.0 | 1.96 |
| 44 | 2025-08-01 04:00 → 2026-01-30 05:00 | period=7, oversold=25.0, overbought=65.0 | 1.16 |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
