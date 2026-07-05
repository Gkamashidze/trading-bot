# Walk-Forward Backtest — spy_rsi_mean_reversion on SPY

_Generated: 2026-07-05 19:06 UTC · Out-of-sample span: 1995-01-27 05:00 → 2026-07-02 04:00 · 62 walk-forward windows_

## Verdict

❌ No demonstrated edge. Out-of-sample the strategy returned +346.9% vs buy-and-hold +2637.1% (-2290.2 pts). It did not beat simply holding the asset after costs.

> **Methodology.** Parameters are grid-searched on each rolling *train* window and
> applied only to the following *test* window it never saw. Every test segment's
> signals are concatenated and executed once through the realistic fill model
> (taker fees + spread/slippage), so this is a true out-of-sample result with no
> look-ahead and no in-sample curve-fitting. The benchmark is buy-and-hold over
> the identical out-of-sample span (one entry fee).

## Out-of-sample vs buy-and-hold

| Metric | Strategy (OOS) | Buy & Hold |
|---|---|---|
| Net return % | +346.89 | +2637.06 |
| CAGR % | +4.89 | +11.12 |
| Sharpe | 0.39 | 0.65 |
| Sortino | 0.33 | 0.83 |
| Max drawdown % | -36.50 | -55.19 |
| Calmar | 0.13 | 0.20 |
| Win rate % | 77.1 | 100.0 |
| Profit factor | 3.08 | — |
| Trades | 96 | 1 |
| Exposure % | 40.1 | 100.0 |
| Fees paid ($) | 3876.29 | — |

## Per-window parameter selection

| # | Test window | Chosen params | Train Sharpe |
|---|---|---|---|
| 0 | 1995-01-27 05:00 → 1995-07-27 04:00 | period=14, oversold=35.0, overbought=65.0 | 1.93 |
| 1 | 1995-07-28 04:00 → 1996-01-25 05:00 | period=7, oversold=30.0, overbought=75.0 | 1.31 |
| 2 | 1996-01-26 05:00 → 1996-07-25 04:00 | period=7, oversold=30.0, overbought=75.0 | 1.40 |
| 3 | 1996-07-26 04:00 → 1997-01-23 05:00 | period=7, oversold=30.0, overbought=65.0 | 1.39 |
| 4 | 1997-01-24 05:00 → 1997-07-24 04:00 | period=7, oversold=30.0, overbought=65.0 | 2.12 |
| 5 | 1997-07-25 04:00 → 1998-01-23 05:00 | period=7, oversold=30.0, overbought=65.0 | 2.01 |
| 6 | 1998-01-26 05:00 → 1998-07-24 04:00 | period=7, oversold=25.0, overbought=75.0 | 1.76 |
| 7 | 1998-07-27 04:00 → 1999-01-25 05:00 | period=7, oversold=30.0, overbought=75.0 | 1.52 |
| 8 | 1999-01-26 05:00 → 1999-07-26 04:00 | period=7, oversold=30.0, overbought=65.0 | 0.94 |
| 9 | 1999-07-27 04:00 → 2000-01-24 05:00 | period=7, oversold=35.0, overbought=65.0 | 0.99 |
| 10 | 2000-01-25 05:00 → 2000-07-24 04:00 | period=7, oversold=35.0, overbought=65.0 | 1.03 |
| 11 | 2000-07-25 04:00 → 2001-01-23 05:00 | period=7, oversold=35.0, overbought=65.0 | 0.89 |
| 12 | 2001-01-24 05:00 → 2001-07-24 04:00 | period=7, oversold=25.0, overbought=65.0 | 1.15 |
| 13 | 2001-07-25 04:00 → 2002-01-29 05:00 | period=7, oversold=25.0, overbought=65.0 | 0.71 |
| 14 | 2002-01-30 05:00 → 2002-07-30 04:00 | period=7, oversold=25.0, overbought=65.0 | 0.34 |
| 15 | 2002-07-31 04:00 → 2003-01-29 05:00 | period=7, oversold=25.0, overbought=65.0 | -0.56 |
| 16 | 2003-01-30 05:00 → 2003-07-30 04:00 | period=7, oversold=25.0, overbought=65.0 | -0.41 |
| 17 | 2003-07-31 04:00 → 2004-01-29 05:00 | period=7, oversold=35.0, overbought=70.0 | -0.18 |
| 18 | 2004-01-30 05:00 → 2004-07-30 04:00 | period=7, oversold=35.0, overbought=70.0 | -0.04 |
| 19 | 2004-08-02 04:00 → 2005-01-28 05:00 | period=7, oversold=25.0, overbought=70.0 | 0.66 |
| 20 | 2005-01-31 05:00 → 2005-07-29 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.52 |
| 21 | 2005-08-01 04:00 → 2006-01-30 05:00 | period=7, oversold=35.0, overbought=75.0 | 1.46 |
| 22 | 2006-01-31 05:00 → 2006-07-31 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.12 |
| 23 | 2006-08-01 04:00 → 2007-01-31 05:00 | period=7, oversold=35.0, overbought=70.0 | 1.33 |
| 24 | 2007-02-01 05:00 → 2007-08-01 04:00 | period=7, oversold=35.0, overbought=70.0 | 0.98 |
| 25 | 2007-08-02 04:00 → 2008-01-31 05:00 | period=7, oversold=35.0, overbought=65.0 | 0.84 |
| 26 | 2008-02-01 05:00 → 2008-07-31 04:00 | period=7, oversold=35.0, overbought=70.0 | 0.40 |
| 27 | 2008-08-01 04:00 → 2009-01-30 05:00 | period=7, oversold=25.0, overbought=65.0 | 0.12 |
| 28 | 2009-02-02 05:00 → 2009-07-31 04:00 | period=7, oversold=25.0, overbought=65.0 | -0.02 |
| 29 | 2009-08-03 04:00 → 2010-02-01 05:00 | period=7, oversold=25.0, overbought=65.0 | -0.07 |
| 30 | 2010-02-02 05:00 → 2010-08-02 04:00 | period=7, oversold=35.0, overbought=75.0 | -0.07 |
| 31 | 2010-08-03 04:00 → 2011-01-31 05:00 | period=7, oversold=35.0, overbought=75.0 | 0.14 |
| 32 | 2011-02-01 05:00 → 2011-08-01 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.48 |
| 33 | 2011-08-02 04:00 → 2012-01-31 05:00 | period=7, oversold=35.0, overbought=70.0 | 1.50 |
| 34 | 2012-02-01 05:00 → 2012-07-31 04:00 | period=7, oversold=25.0, overbought=65.0 | 0.68 |
| 35 | 2012-08-01 04:00 → 2013-02-01 05:00 | period=7, oversold=25.0, overbought=75.0 | 0.68 |
| 36 | 2013-02-04 05:00 → 2013-08-02 04:00 | period=14, oversold=35.0, overbought=65.0 | 0.79 |
| 37 | 2013-08-05 04:00 → 2014-02-03 05:00 | period=7, oversold=35.0, overbought=65.0 | 1.53 |
| 38 | 2014-02-04 05:00 → 2014-08-04 04:00 | period=7, oversold=35.0, overbought=75.0 | 1.47 |
| 39 | 2014-08-05 04:00 → 2015-02-03 05:00 | period=7, oversold=35.0, overbought=75.0 | 1.93 |
| 40 | 2015-02-04 05:00 → 2015-08-04 04:00 | period=7, oversold=35.0, overbought=70.0 | 1.58 |
| 41 | 2015-08-05 04:00 → 2016-02-03 05:00 | period=14, oversold=35.0, overbought=65.0 | 2.06 |
| 42 | 2016-02-04 05:00 → 2016-08-03 04:00 | period=7, oversold=25.0, overbought=65.0 | 0.86 |
| 43 | 2016-08-04 04:00 → 2017-02-02 05:00 | period=14, oversold=35.0, overbought=65.0 | 1.26 |
| 44 | 2017-02-03 05:00 → 2017-08-03 04:00 | period=7, oversold=25.0, overbought=65.0 | 0.69 |
| 45 | 2017-08-04 04:00 → 2018-02-02 05:00 | period=7, oversold=25.0, overbought=75.0 | 0.80 |
| 46 | 2018-02-05 05:00 → 2018-08-03 04:00 | period=7, oversold=30.0, overbought=70.0 | 1.76 |
| 47 | 2018-08-06 04:00 → 2019-02-05 05:00 | period=7, oversold=25.0, overbought=65.0 | 1.19 |
| 48 | 2019-02-06 05:00 → 2019-08-06 04:00 | period=7, oversold=25.0, overbought=65.0 | 0.86 |
| 49 | 2019-08-07 04:00 → 2020-02-05 05:00 | period=7, oversold=25.0, overbought=65.0 | 0.84 |
| 50 | 2020-02-06 05:00 → 2020-08-05 04:00 | period=7, oversold=25.0, overbought=70.0 | 1.01 |
| 51 | 2020-08-06 04:00 → 2021-02-04 05:00 | period=7, oversold=25.0, overbought=70.0 | 0.21 |
| 52 | 2021-02-05 05:00 → 2021-08-05 04:00 | period=7, oversold=30.0, overbought=75.0 | 0.66 |
| 53 | 2021-08-06 04:00 → 2022-02-03 05:00 | period=7, oversold=35.0, overbought=75.0 | 0.87 |
| 54 | 2022-02-04 05:00 → 2022-08-05 04:00 | period=7, oversold=35.0, overbought=75.0 | 0.58 |
| 55 | 2022-08-08 04:00 → 2023-02-06 05:00 | period=7, oversold=35.0, overbought=75.0 | 0.76 |
| 56 | 2023-02-07 05:00 → 2023-08-08 04:00 | period=7, oversold=35.0, overbought=75.0 | 0.34 |
| 57 | 2023-08-09 04:00 → 2024-02-07 05:00 | period=14, oversold=35.0, overbought=65.0 | 0.65 |
| 58 | 2024-02-08 05:00 → 2024-08-08 04:00 | period=14, oversold=35.0, overbought=65.0 | 0.95 |
| 59 | 2024-08-09 04:00 → 2025-02-10 05:00 | period=14, oversold=35.0, overbought=65.0 | 0.95 |
| … | (2 more windows) | | |

---
_Reproduce: `python scripts/run_walk_forward.py`. Results are not curve-fit; if the
strategy loses to buy-and-hold, this report says so._
