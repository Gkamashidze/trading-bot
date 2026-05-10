# Strategy Quality Roadmap

**Status:** FUTURE RESEARCH BACKLOG — not yet started  
**Prerequisite:** Evidence store stable, paper trading running cleanly for 14+ days  
**Live trading:** DISABLED — `live_trading_enabled = false` throughout all research phases  
**Relationship to ROADMAP_LIVE.md:** That document covers operational readiness (gates, credentials,
runbooks). This document covers strategy quality evolution — how we go from SMA/RSI baseline to
genuine alpha. Both must be completed before live trading.

> Every strategy in this document starts in Research.  
> No strategy reaches Paper unless it passes Backtest Quality Gates (Section 9).  
> No strategy reaches Micro-Live unless it passes Paper Testing Requirements (Section 10).  
> The risk engine is never bypassed. The promotion pipeline is never skipped.

---

## 1. Strategy Classification — Current Baseline

### 1.1 SMA Crossover (sma_v1.x.x)

| Property | Value |
|---|---|
| Parameters | fast=20, slow=50, timeframe=1h |
| Regime fit | Trending markets only |
| Known weakness | Whipsaw in mean-reverting / sideways markets |
| Classification | **Baseline / Infrastructure Canary** |
| Production alpha | No — insufficient edge in live conditions |
| Benchmark use | Yes — every future strategy must beat SMA/RSI in risk-adjusted terms |

### 1.2 RSI Mean-Reversion (rsi_v1.x.x)

| Property | Value |
|---|---|
| Parameters | period=14, oversold=30, overbought=70, timeframe=1h |
| Regime fit | Sideways / mean-reverting markets |
| Known weakness | Fails in strong trends (RSI stays overbought/oversold) |
| Classification | **Baseline / Infrastructure Canary** |
| Production alpha | No — insufficient edge in live conditions |
| Benchmark use | Yes — every future strategy must beat SMA/RSI in risk-adjusted terms |

### 1.3 The Infrastructure Canary Role

SMA/RSI serve a second purpose beyond benchmarking: **infrastructure health detection**.

If SMA/RSI paper Sharpe deteriorates unexpectedly, the root cause is more likely an infrastructure
regression (stale feed, fill simulation bug, slippage miscalculation, timing drift) than genuine
strategy decay. When decay alerts fire on SMA/RSI, investigate infrastructure first.

This makes SMA/RSI permanently useful even after better strategies are deployed.

**Rule:** Do NOT retire SMA/RSI strategies. Keep them running in paper mode indefinitely as
infrastructure canaries. They do not consume real capital.

---

## 2. Regime-Aware Strategy Framework

### 2.1 Why Regime Detection Comes First

No single strategy outperforms across all market conditions. The correct engineering response is:
detect the regime, then activate the strategy best suited to it — not build a strategy that "works everywhere."

Regime detection must precede strategy deployment. A strategy deployed in the wrong regime will
lose money even if the strategy logic is correct.

### 2.2 Regime Taxonomy (Asset-Specific)

**BTC/USDT regimes:**

| Regime | Detection Signals | Strategy Preference |
|---|---|---|
| Trend Up | Price > SMA200 daily, SMA50 > SMA200, funding positive | Trend pullback, momentum |
| Trend Down | Price < SMA200 daily, SMA50 < SMA200, funding negative | Inverse momentum, reduce exposure |
| Mean-Reverting | ADX < 20, price oscillating around SMA50, funding near zero | RSI mean-reversion |
| High Volatility | ATR(14) > 2× 90-day median ATR | Reduce all position sizes; tighten stops |
| Funding Stress | Binance funding rate > +0.1% per 8h or < -0.05% per 8h | Contrarian bias; caution on longs |
| Fear & Greed Extreme | F&G < 20 (Extreme Fear) or > 80 (Extreme Greed) | Contrarian signal overlay |
| Risk-Off Macro | DXY > 90-day high AND BTC-SPY 30-day correlation > 0.7 | Reduce all exposure |

**SPY / QQQ / SOXX ETF regimes:**

| Regime | Detection Signals | Strategy Preference |
|---|---|---|
| Bull Trend | SPY > SMA200 daily, VIX < 20 | Trend following, momentum |
| Bear / Risk-Off | SPY < SMA200 daily OR VIX > 30 | Reduce all ETF exposure |
| Consolidation | SPY within 3% of SMA50, VIX 15-20 | Mean-reversion on SOXX/QQQ |
| Fed Decision Window | Within 3 days of FOMC meeting | Reduce sizing; avoid new entries |
| Earnings Season | SPY constituent earnings density > 20% per week | Reduce SOXX/QQQ sizing |
| VIX Spike | VIX > 2× 30-day average | Halt new entries; let positions run to stop |

**Cross-asset overlay:**

| Signal | Calculation | Effect |
|---|---|---|
| BTC-SPY correlation spike | 30-day rolling correlation > 0.7 | Risk-off for all assets |
| DXY breakout | DXY > 90-day high | Reduce BTC and equity exposure |
| Yield curve inversion | 2Y > 10Y sustained | Reduce equity exposure |

### 2.3 Regime Implementation Phases

**Phase 1 (Research):** Manual regime labeling on historical data. Backtest each strategy segmented by regime. Measure regime-specific Sharpe, drawdown, hit rate.

**Phase 2 (Infrastructure):** `RegimeDetector` interface in `trading_bot/core/contracts.py`. Publish `RegimeChangeEvent` on event bus. Strategies subscribe to regime events.

**Phase 3 (Production):** Regime-conditional strategy weights in capital policy. Automated regime logging and audit trail. ROADMAP_LIVE.md §3.4 covers the capital allocation side.

**Interface (Phase 2 target):**
```python
class MarketRegime(StrEnum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    FUNDING_STRESS = "funding_stress"   # crypto only
    RISK_OFF_MACRO = "risk_off_macro"
    UNDEFINED = "undefined"

@dataclass(frozen=True)
class RegimeChangeEvent:
    symbol: str
    previous_regime: MarketRegime
    current_regime: MarketRegime
    timestamp: datetime              # UTC-aware
    confidence: float                # 0.0–1.0
    trigger_signals: dict[str, Any]  # which signals caused the change
```

**Regime detector must be backtested** before use in production. Measure: how often does the
classifier correctly label the regime that produced the best strategy performance in hindsight?
Target: > 60% directional accuracy on a held-out test set.

---

## 3. Trend Pullback Strategy (Candidate)

### 3.1 Hypothesis

In trending markets, short-term pullbacks to a moving average or oversold RSI provide higher
probability entries than breakout entries. The trend filter prevents trading against the dominant direction.
ATR-based sizing adjusts for volatility, and ATR-based stops prevent large losses.

### 3.2 Design (BTC/USDT variant)

**Trend Filter (daily timeframe):**
- Price above daily SMA200 AND
- Daily SMA50 > daily SMA200 (golden cross confirmation)
- If either fails: strategy is inactive. No entries.

**Entry (1h timeframe):**
- RSI(14) drops below 35 on 1h chart (pullback confirmed)
- RSI(14) crosses back above 40 on the next close (recovery confirmed)
- Price remains above daily SMA50 on the 1h chart (pullback didn't break structure)
- Volume at entry bar is not abnormally low (< 0.5× 20-bar rolling average volume = skip)

**Pre-Trade Checks:**
- Market data fresh (last tick < 5 seconds old)
- Spread ≤ configurable threshold (default 0.1% for BTC/USDT)
- Expected move (ATR-estimated) > spread + fees + slippage buffer (see Section 7)
- Feature flag `trend_pullback_enabled` = true
- Regime: `TREND_UP` only

**Exits:**
- Stop-loss: entry price − 1.5 × ATR(14, 1h)
- Take-profit: entry price + 3.0 × ATR(14, 1h) (3R target; 2:1 minimum)
- Trailing stop: activate after 1R profit; trail at 1.0 × ATR
- Max holding period: 48 hours regardless of outcome
- Regime-change exit: if regime shifts from TREND_UP → any other regime mid-trade, exit at market

**Position Sizing:**
- Risk per trade: 1% of available capital (configurable, capped by capital policy)
- Position size: `risk_amount / stop_distance_in_price`
- Stop distance: `1.5 × ATR(14, 1h)` at entry
- Hard cap: never exceed capital policy's per-trade limit regardless of ATR size

**Exit Reason Tracking:**
Every closed trade must record: `stop_loss | take_profit | trailing_stop | max_holding | regime_change | manual | signal_invalidation`

### 3.3 Design (ETF variant — SPY/QQQ/SOXX)

**Trend Filter:**
- SPY > daily SMA200 (macro filter for all ETF trades)
- For SOXX specifically: QQQ > daily SMA50 as tech sector filter

**Entry (1d timeframe — ETFs use daily bars, not 1h):**
- RSI(14, daily) drops below 38 and crosses back above 43
- Price remains above SPY SMA50 (macro structure intact)
- Not within 3 days of FOMC meeting
- Not in earnings season with density > 20%

**Exits:**
- Stop-loss: 1.5 × ATR(14, daily)
- Take-profit: 2.5 × ATR(14, daily) (equities trend less aggressively than crypto)
- Max holding period: 15 trading days
- Regime exit: if VIX > 30 or SPY < SMA200, exit immediately

**Market Hours:** Only ETF entries during regular session (09:30–15:30 ET). No pre/post-market entries. Enforced by `pandas_market_calendars`.

### 3.4 Status

**Stage:** Research only — not implemented  
**Feature flag:** `trend_pullback_enabled = false`  
**Next step:** Backtest on BTC/USDT using 2021–2024 historical data (full market cycle including crash)  
**Promotion path:** Research → Backtest Gate → Shadow → Paper (30 days) → Evidence Review → Micro-Live gate (ROADMAP_LIVE.md §4)

---

## 4. Multi-Timeframe Confirmation Research Plan

### 4.1 Motivation

Single-timeframe strategies miss structural context. A 1h RSI oversold signal in a daily downtrend
is a trap, not an opportunity. Multi-timeframe confirmation reduces false signals at the cost of
fewer entries.

### 4.2 Timeframe Hierarchy (BTC/USDT)

| Timeframe | Role | Data Requirement |
|---|---|---|
| Daily | Trend direction + regime | Daily OHLCV (already available) |
| 4h | Market structure (higher highs/lows) | 4h OHLCV (needs ingestion job) |
| 1h | Entry timing | 1h OHLCV (already available) |
| 15m | Optional: precise entry timing | 15m OHLCV (higher storage cost) |

**Ingestion requirement:** Add 4h bar aggregation to the scheduler. Either aggregate from 1h bars
(already available) or add a dedicated 4h WebSocket stream. Aggregation from 1h is simpler.

### 4.3 Lookahead Bias Prevention (Critical)

The most common backtest error in multi-timeframe systems:

- **Wrong:** use daily SMA200 computed at close of day T to filter a 1h signal generated at 10:00 on day T — the daily bar hasn't closed yet
- **Right:** use daily SMA200 computed at close of day T-1 for all signals on day T

Rule: **A higher-timeframe indicator is only valid after its bar has closed.** At 10:00 on day T, the last confirmed daily bar is T-1. At 00:01 UTC day T+1, daily bar T is confirmed and usable for day T+1.

Implementation: all OHLCV bars carry `bar_close_time` (UTC-aware). Multi-timeframe logic must only consume bars with `bar_close_time < signal_timestamp`.

### 4.4 Research Priorities

1. **4h structure filter** — backtest SMA/RSI with and without 4h trend confirmation. Measure: does it reduce whipsaw losses more than it reduces winners?
2. **Daily-1h entry alignment** — measure false positive rate of 1h signals that contradict daily trend
3. **15m timing value** — only worth adding if 4h+1h combination is validated first

---

## 5. Entry Logic Catalogue (Research Queue)

All items below require isolated backtests. Each must be compared to SMA/RSI baseline on same historical period.

| Entry Signal | Description | Priority | Notes |
|---|---|---|---|
| RSI Recovery Cross | RSI < 35 then crosses above 40 | High | Trend Pullback uses this; test in isolation first |
| Pullback to EMA21 | Price touches EMA21 and bounces on 1h | High | Works well with trend filter |
| BB Mean Reversion | Price < lower Bollinger Band (2σ) and closes inside | Medium | Classic; needs regime filter |
| MACD Cross Confirmation | MACD line crosses signal line from below | Medium | Lagging; test as confirmation not primary |
| Volume Surge Entry | Volume > 2× 20-bar average on bullish close | Medium | Useful for BTC; less reliable for ETFs |
| Volatility Compression | ATR at 60-day low before breakout | Medium | Breakout type; separate strategy category |
| Breakout + Retest | Price breaks above resistance, retests it, holds | Low | Requires structure detection |
| OI Change Entry | Open interest drops then rises (futures only) | Low | BTC futures; needs OI data integration |

**Backtest requirement for each:** minimum 200 trades in the sample, regime-segmented results, comparison to SMA/RSI baseline Sharpe, out-of-sample validation on held-out 20% of data.

---

## 6. Exit Logic Framework

### 6.1 Exit Type Catalogue

| Exit Type | When to Use | Notes |
|---|---|---|
| Fixed stop-loss | Simple baseline | Worst type; doesn't account for volatility |
| ATR stop-loss | Default for all strategies | Use 1.0–2.0 × ATR(14) |
| Take-profit R-multiple | 2R or 3R relative to stop distance | Forces positive expectancy |
| Trailing stop | After price moves in favor by 1R | Locks in profit |
| Time-based exit | Max holding period | Prevents dead positions |
| Regime-change exit | Regime shifts against trade | Fastest exit when structure breaks |
| Volatility spike exit | ATR doubles within 1 session | Reduces tail risk |
| Signal invalidation exit | Entry signal condition reverses | RSI re-enters overbought zone |

### 6.2 Exit Reason Distribution Requirement

Every backtest report must include exit reason breakdown:
```
exit_reason_distribution:
  stop_loss: 35%
  take_profit: 28%
  trailing_stop: 20%
  time_exit: 10%
  regime_change: 5%
  signal_invalidation: 2%
```

A backtest where > 50% of exits are stop-loss exits has a poor entry model, not just a poor exit model. Investigate the entry.

### 6.3 Default Exit Stack (All Strategies)

Every strategy must define all of these before Paper promotion:
1. Hard stop-loss (ATR-based or fixed)
2. Minimum take-profit target (positive expectancy required: `win_rate × avg_win > (1 - win_rate) × avg_loss`)
3. Max holding period
4. Regime-change exit condition

Optional (must be justified in the Research-to-Production Contract):
5. Trailing stop
6. Volatility spike exit
7. Signal invalidation exit

---

## 7. Transaction-Cost-Aware Entry Filter

### 7.1 Minimum Expected Edge Check

A signal is only tradable if the expected gross move exceeds the total transaction cost.

```
total_transaction_cost = spread + maker_fee + taker_fee + estimated_slippage + latency_buffer

tradable = expected_gross_move > total_transaction_cost × safety_margin
```

**Default values (BTC/USDT, configurable):**
- Spread: measured at signal time from order book
- Taker fee: 0.04% (Binance BNB discount rate)
- Estimated slippage: 0.03% for market orders under normal liquidity
- Latency buffer: 0.01% (accounts for price drift from signal to fill)
- Safety margin: 1.5× (expected move must exceed costs by 50%)

For market orders: always use taker fee. Never assume maker fill for execution.

**Implementation location:** `trading_bot/execution/pre_trade.py` → `EdgeFilter.check()`

**Rule:** If `EdgeFilter.check()` returns False, the order is not submitted. Signal is recorded as "rejected: insufficient edge." Rejection rate is a monitored metric.

### 7.2 Rejection Rate Monitoring

Target rejection rate: 5–20% of signals. If < 5%: edge threshold may be too permissive. If > 40%: strategy generates too many marginal signals.

---

## 8. Volatility-Adjusted Position Sizing

### 8.1 Sizing Formula

```
risk_amount = account_equity × max_risk_per_trade_pct
stop_distance = stop_loss_price_distance_in_asset_units
raw_position_size = risk_amount / stop_distance
```

**Adjustments applied sequentially:**
1. ATR scale: if ATR > 2× 90-day median ATR → scale `raw_position_size` × 0.5
2. Drawdown scale: if current drawdown > 10% → scale × 0.7; if > 20% → scale × 0.4
3. Regime scale: HIGH_VOLATILITY regime → additional × 0.6
4. Signal strength scale (if available): scale linearly from 0.7 to 1.0 based on signal confidence

**Final position size = all four adjustments applied multiplicatively, then capped by:**
- Capital policy `per_trade_limit` (absolute max)
- Capital policy `max_open_risk` (sum of all open positions' risk)
- Risk engine approval

The risk engine always has final veto. No sizing formula output bypasses `RiskEngine.evaluate()`.

### 8.2 Implementation Location

`trading_bot/risk/capital_policy.py` — add `volatility_adjusted_size()` method.  
Must remain backwards-compatible with existing `check()` interface.

---

## 9. Backtest Quality Gate

### 9.1 Required Checks (All Must Pass)

| Check | Criterion | Enforcement |
|---|---|---|
| No lookahead bias | All indicators use only data available before signal timestamp | Code review + replay test |
| Realistic fills | Market orders use arrival mid + slippage; limit orders use passive fill assumption | Backtest engine config |
| Fees included | Taker fee applied on every trade | Non-negotiable |
| Slippage model | Per-symbol slippage estimate (not zero) | Backtest engine config |
| Sufficient trades | ≥ 100 completed round-trips in sample period | Hard reject if fewer |
| Out-of-sample validation | ≥ 20% of data reserved for OOS test; OOS Sharpe ≥ 0.5 × in-sample Sharpe | Hard reject if OOS degrades > 50% |
| Regime breakdown | Performance reported per regime label | Required in report |
| Benchmark comparison | Sharpe vs SMA/RSI on same period | Required in report |
| Parameter stability | Tested with ±20% perturbation of all parameters; results should not collapse | Hard reject if fragile |
| Data lineage | Backtest records dataset snapshot ID used | Required |
| Market cycle coverage | Must include at least one crash and one rally period | Required |
| Crypto-specific | Funding rate cost included for BTC perpetual positions | Required for BTC futures |

### 9.2 Report Format (Minimum Required)

```
strategy: trend_pullback_v1
version: 0.1.0
backtest_period: 2021-01-01 / 2024-12-31
in_sample_period: 2021-01-01 / 2024-03-31
out_of_sample_period: 2024-04-01 / 2024-12-31
dataset_snapshot_id: <uuid>

in_sample:
  sharpe_ratio: 1.42
  sortino_ratio: 2.01
  max_drawdown: -14.2%
  calmar_ratio: 0.99
  total_trades: 187
  win_rate: 48%
  avg_win: 3.2%
  avg_loss: -1.9%
  expectancy: +0.63%
  exit_reason_distribution: {stop_loss: 34%, take_profit: 31%, trailing_stop: 22%, time_exit: 9%, regime_change: 4%}

out_of_sample:
  sharpe_ratio: 0.98          # > 0.5 × in-sample: PASS
  max_drawdown: -17.1%
  total_trades: 49

regime_breakdown:
  trend_up: {sharpe: 1.87, trades: 121}
  mean_reverting: {sharpe: -0.34, trades: 44}  # WARNING: negative in MR regime
  high_volatility: {sharpe: 0.21, trades: 22}

benchmark_comparison:
  sma_crossover_same_period_sharpe: 0.61
  rsi_same_period_sharpe: 0.44
  strategy_vs_baseline: +0.37 Sharpe (PASS: exceeds baseline)

parameter_stability: PASS (±20% perturbation degrades Sharpe by 12%, within threshold)
```

### 9.3 Automatic Rejection Criteria

Backtest is automatically rejected (cannot advance to Shadow) if any of:
- OOS Sharpe < 0.5 × in-sample Sharpe
- Total trades < 100 in-sample
- Strategy Sharpe < both SMA/RSI baselines on same period
- Parameter stability: ±20% perturbation collapses Sharpe by > 40%
- No regime breakdown provided
- No dataset snapshot ID recorded
- Funding rate not included for BTC futures backtest

---

## 10. Paper Testing Requirements for New Strategies

Before any new strategy can be reviewed for Micro-Live, it must complete:

| Requirement | Threshold |
|---|---|
| Calendar days in paper | ≥ 30 days |
| Completed round-trip trades | ≥ 30 trades |
| Reconciliation | Clean every day (OMS position = paper position) |
| Max paper drawdown | Within 1.5× worst backtest drawdown |
| Paper/backtest parity | Sharpe within 40% of backtest Sharpe on same market period |
| Rejected signal rate | Between 5% and 40% (EdgeFilter working) |
| Slippage | Paper slippage estimate ≤ 1.5× modeled slippage |
| Critical incidents | Zero unresolved P0/P1 incidents |
| SMA/RSI canary | SMA/RSI concurrent paper performance consistent with history (infrastructure health) |
| Operator review | Risk officer and operator both signed off |

**Parity check methodology:** Replay the same signal timestamp window through the backtest engine
and through the paper trading record. Compare trade count, entry prices (± slippage), exit reasons.
Divergence > 20% on any metric triggers investigation before promotion.

---

## 11. Walk-Forward Optimization Workflow

### 11.1 Manual Walk-Forward (Research Phase)

Before building automation, the researcher runs walk-forward manually:

```
Full data: 2021-01-01 → 2024-12-31 (4 years)

Window 1: Train 2021-01 to 2023-06, Test 2023-07 to 2023-12
Window 2: Train 2021-01 to 2023-12, Test 2024-01 to 2024-06
Window 3: Train 2021-01 to 2024-06, Test 2024-07 to 2024-12

For each window:
  - Optimize parameters on Train (grid search or Bayesian optimization)
  - Evaluate optimized parameters on Test (no further optimization)
  - Record: optimal parameters, test Sharpe, parameter values
```

**Overfitting warning signs:**
- Optimal parameters shift dramatically window to window
- In-sample Sharpe >> out-of-sample Sharpe consistently
- A small number of lucky trades explain most of the in-sample profit

### 11.2 Parameters to Test

| Parameter | SMA Crossover | RSI MR | Trend Pullback |
|---|---|---|---|
| Fast MA period | 10–30 | — | — |
| Slow MA period | 40–80 | — | — |
| RSI period | — | 10–20 | 10–20 |
| RSI oversold | — | 25–35 | 30–40 |
| RSI recovery | — | 35–50 | 38–48 |
| ATR period | — | — | 10–20 |
| Stop multiplier | — | — | 1.0–2.5 |
| TP R-multiple | — | — | 1.5–4.0 |
| Trend filter period | — | — | 150–250 (SMA daily) |

**Automation (ROADMAP_LIVE.md §3.5):** Walk-forward automation is a production feature.
Research-phase walk-forward is done manually using `trading_bot/research/experiment.py`.
Automation comes after the manual process is validated.

### 11.3 Experiment Artifacts

Every walk-forward run must store:
- Dataset snapshot ID (which data was used)
- Parameter grid explored
- Per-window results (not just aggregate)
- Random seed (for reproducibility)
- Researcher name and date
- Conclusion: stable / unstable / rejected

Storage: `trading_bot/research/experiment.py` → `ExperimentRecord` → database.

---

## 12. Strategy Decay Detection

**Implementation:** `trading_bot/monitoring/decay.py` — already implemented.

This section defines the per-strategy thresholds and escalation rules that `DecayConfig` should be parameterized with.

### 12.1 Decay Metrics and Thresholds

| Metric | Advisory | Warning | Critical |
|---|---|---|---|
| Rolling Sharpe (30d) | < 0.5 × backtest Sharpe | < 0.0 | < -0.5 × backtest Sharpe |
| Max drawdown (30d) | > 1.3 × backtest max DD | > 1.7 × | > 2.0 × |
| Hit rate (30d) | < 0.9 × backtest win rate | < 0.8 × | < 0.65 × |
| Signal frequency | < 0.6 × backtest avg or > 2.5 × | < 0.4 × or > 4 × | < 0.2 × or > 6 × |
| Slippage (30d) | > 1.3 × modeled | > 1.7 × | > 2.5 × |
| Paper/live divergence | > 15% on Sharpe | > 30% | > 50% |
| Regime mismatch | Strategy active in wrong regime | — | All signals in wrong regime |

### 12.2 Decay Escalation Actions

| Severity | Action |
|---|---|
| Advisory | Log warning; include in weekly decay report |
| Warning | Operator notification; reduce position sizes by 30%; freeze promotion |
| Critical | Operator notification P1; move to shadow mode; require investigation before any trading |

**Rule:** A strategy with an active Critical decay alert cannot be promoted. A strategy with three
consecutive Warning periods must be reviewed before promotion continues.

### 12.3 SMA/RSI Canary Decay Interpretation

When SMA/RSI decay alerts fire:
1. First, check infrastructure: feed freshness, fill simulation accuracy, reconciliation
2. If infrastructure is clean: declare regime mismatch (not strategy decay)
3. Regime mismatch is expected — SMA performs poorly in mean-reverting markets
4. Only escalate if decay persists across multiple regime types simultaneously

---

## 13. Strategy Comparison Dashboard (Future)

This section defines the requirements for a future dashboard panel in `trading_bot/dashboard/app.py`.

### 13.1 Required Views

**Per-strategy performance panel:**
- Gross P&L and net P&L (after fees)
- Sharpe, Sortino, Calmar ratios (rolling 30d and all-time)
- Max drawdown (current and worst)
- Trade count and win rate
- Average win and average loss
- Rejection rate (EdgeFilter)
- Slippage actual vs modeled
- Exit reason distribution (pie/bar chart)
- Regime breakdown table (which regime produced the best/worst results)

**Strategy comparison panel:**
- Side-by-side: all active strategies + SMA/RSI baseline
- Equity curves on same chart
- Drawdown curves on same chart

**Promotion status panel:**
- Current promotion stage for each strategy
- Days in current stage
- Pending gate requirements
- Decay alert status

**Implementation:** Add to `trading_bot/dashboard/app.py` as a new `/strategies` route.
Requires data from `trading_bot/monitoring/decay.py` + paper trade records.

---

## 14. Research-to-Production Contract

Every new strategy must complete this contract before entering Shadow phase.
The contract is version-controlled in `trading_bot/docs/strategies/<strategy_name>.yaml`.

### 14.1 Contract Schema

```yaml
# trading_bot/docs/strategies/trend_pullback_v1.yaml
strategy:
  name: trend_pullback
  version: 0.1.0
  owner: <github_handle>
  created: 2026-05-11
  review_date: 2026-11-11    # 6 months; must be re-reviewed after expiry

hypothesis: |
  In established uptrends (price above daily SMA200), short-term pullbacks confirmed
  by RSI recovery provide higher-probability entries than breakout entries.
  The trend filter prevents shorting into strong trends. ATR sizing controls tail risk.

target_assets:
  - BTC/USDT
  - SPY
  - QQQ
  - SOXX

regime_fit:
  - trend_up

regime_avoid:
  - mean_reverting
  - high_volatility
  - funding_stress

parameters:
  trend_filter_period: 200      # daily SMA
  rsi_period: 14
  rsi_entry_low: 35
  rsi_entry_cross: 40
  atr_period: 14
  stop_multiplier: 1.5
  tp_r_multiple: 3.0
  max_holding_hours: 48

dataset_snapshot_ids:
  - <uuid_of_backtest_dataset>

backtest_results:
  period: "2021-01-01/2024-12-31"
  sharpe: 1.42
  max_drawdown: -14.2%
  total_trades: 187
  win_rate: 48%
  out_of_sample_sharpe: 0.98
  parameter_stability: pass

walk_forward_results:
  windows: 3
  conclusion: stable
  max_parameter_shift: 12%      # how much optimal params shifted window to window

expected_transaction_costs:
  spread_pct: 0.05
  taker_fee_pct: 0.04
  estimated_slippage_pct: 0.03
  latency_buffer_pct: 0.01
  total_round_trip_pct: 0.26    # spread + 2×(fee + slippage + latency)

risk_assumptions:
  - Trend filter holds during holding period
  - BTC liquidity remains normal (bid-ask spread < 0.1%)
  - No exchange outage during open position

known_failure_modes:
  - Flash crash: trend filter bypassed by sudden drop; stop-loss fires, expected loss 1.5 ATR
  - Prolonged consolidation: no entries, no losses
  - Funding rate spike against position: adds hidden cost not modeled in spot backtest

promotion_status: research
feature_flag: trend_pullback_enabled
```

### 14.2 Contract Validation Rule

No strategy may advance to Shadow phase without a complete contract where all required fields are populated and `backtest_results.out_of_sample_sharpe` passes the Backtest Quality Gate (Section 9).

This validation should be enforced programmatically by the promotion pipeline.

---

## 15. Strategy Retirement Policy

**Cross-reference:** ROADMAP_LIVE.md §3.10 defines the demotion procedure and graveyard.
This section adds the specific criteria and process for our project.

### 15.1 Retirement Triggers

A strategy must be reviewed for retirement if any of:

| Trigger | Threshold |
|---|---|
| Review date passed | `review_date` in contract expired; no renewed review within 30 days |
| Sustained decay | Critical decay alert for 14+ consecutive days |
| Excessive drawdown | Drawdown > 2.5× backtest worst drawdown |
| Poor paper/live parity | Sharpe divergence > 50% sustained for 30 days |
| Regime no longer occurring | Regime the strategy requires has not appeared in 90 days |
| Repeated risk violations | 3 or more risk engine rejections within 7 days |
| Operator decision | Documented decision with rationale |

### 15.2 Retirement Process

1. Move strategy to Shadow mode (observe only, no capital)
2. Gracefully close all open positions (never forced liquidation)
3. Write retirement rationale in contract YAML: `retirement_reason`, `retirement_date`
4. Move contract to `trading_bot/docs/strategies/archived/<name>_<version>_<date>.yaml`
5. Post-mortem (mandatory): why did the edge decay? what was learned?
6. Remove feature flag from active rotation (set to false permanently)
7. Keep strategy CODE — retired strategy must remain backtest-reproducible

### 15.3 Auditability Requirement

A retired strategy must be reconstructable: given its dataset snapshot IDs and contract parameters,
anyone must be able to reproduce its backtest results identically. This means:
- Code must not be deleted, only disabled
- Dataset snapshots must be retained
- Random seeds must be recorded in experiment artifacts

---

## Priority and Sequencing

### Recommended Research Order

| Priority | Item | Why First |
|---|---|---|
| 1 | Regime detection (§2) | Prerequisite for all other strategies; affects entry/exit/sizing |
| 2 | Transaction-cost-aware entry (§7) | Removes false edges from all strategies immediately |
| 3 | ATR-based position sizing (§8) | Safer than fixed sizing; easy to implement |
| 4 | Trend Pullback backtest (§3) | Highest-potential candidate strategy |
| 5 | Exit logic framework (§6) | Affects all strategies; exit reason tracking |
| 6 | Backtest quality gate enforcement (§9) | Infrastructure for all future research |
| 7 | Walk-forward manual workflow (§11) | Parameter validation before any promotion |
| 8 | Multi-timeframe research (§4) | Higher data infrastructure cost; do after basics |
| 9 | Strategy comparison dashboard (§13) | Visibility; useful but not blocking |
| 10 | Entry logic catalogue (§5) | Longer research queue; do in parallel with paper |

---

## Related Documents

- `docs/ROADMAP_LIVE.md` — operational readiness gates, walk-forward automation (§3.5), signal decay monitoring (§3.6), TCA calibration (§3.9), strategy retirement procedure (§3.10)
- `docs/PLAN.md` — full development specification (Stages 0–8), promotion pipeline, regime detection (Stage 3)
- `trading_bot/monitoring/decay.py` — strategy decay detection implementation
- `trading_bot/docs/strategies/` — strategy one-pagers and contracts
- `trading_bot/docs/adr/ADR-0007-promotion-pipeline-stages.md` — promotion stage definitions

---

*This document covers strategy quality evolution only. Operational gates, live money rollout, and
infrastructure runbooks are in ROADMAP_LIVE.md. Both documents must be completed before live trading.*  
*Live trading remains DISABLED. `live_trading_enabled = false`.*  
*Last updated: 2026-05-11*
