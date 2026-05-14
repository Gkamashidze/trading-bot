# ROADMAP: Post-Production-Readiness Future Work

**Status:** FUTURE BACKLOG — Not yet started  
**Prerequisite:** All Stages 0–8 in PLAN.md implemented and verified  
**Live trading:** DISABLED. This document describes what must be done before enabling it.  
**Live trading config flag:** `live_trading_enabled = false` — remains false until every gate below passes.

> This document organizes the remaining engineering and operational work that comes **after**
> the core production-readiness roadmap is implemented. It is a forward-looking backlog,
> not a description of current functionality.
>
> Cross-references to PLAN.md are noted where that document already defines related requirements.
> This document adds the operational checklists, sequencing gates, and evidence requirements
> that PLAN.md does not consolidate in one place.

---

## 1. Real Broker/Exchange Production Integration

> **PLAN.md reference:** Stage 5 (Execution Engine), Stage 6 (Safety Layer), Stage 7 (Deployment).
> This section adds the production credential rollout, API hardening, and exchange-specific
> edge cases that are deferred until paper and micro-live gates pass.

### Prerequisites before any of this begins

- [ ] 30+ days of stable paper trading (see Section 4)
- [ ] Zero P0/P1 bugs in the last 14 days of paper trading
- [ ] Reconciliation history clean for 7+ consecutive days
- [ ] All runbooks written and reviewed
- [ ] Post-mortems from chaos drills reviewed and addressed

### 1.1 Production Secrets and Credential Management

- [ ] Migrate API keys from `.env` files to a production secrets provider (e.g., HashiCorp Vault, Doppler, or cloud-native equivalent)
- [ ] Separate read-only key (market data) from trading key (order submission) — never merge scopes
- [ ] Restrict trading API key by IP whitelist (exchange-side setting)
- [ ] Enable withdrawal IP whitelist restriction (separate from trading key)
- [ ] Document and test key rotation procedure — rotation must complete with zero downtime
- [ ] Rotation drill: execute a full key rotation in staging before first live credential use
- [ ] Audit log entry on every key rotation event (actor, timestamp, old key fingerprint, new key fingerprint)

### 1.2 Real Order Placement

- [ ] Implement live `place_order()` — currently raises `NotImplementedError` (PLAN.md constraint)
- [ ] Implement `cancel_order()` with idempotent retry (exchange may confirm cancel after timeout)
- [ ] Implement `replace_order()` / amend (cancel + resubmit pattern if exchange lacks native amend)
- [ ] Implement `get_order_status()` polling fallback when WebSocket fill confirmation is missing
- [ ] All order operations carry correlation ID propagated through from signal to fill
- [ ] All order operations are idempotent via UUID v7 client order ID (PLAN.md: idempotency module)
- [ ] Implement order state machine: `PENDING → SUBMITTED → PARTIALLY_FILLED → FILLED / CANCELLED / REJECTED`
- [ ] Audit log entry on every state transition with full payload snapshot

### 1.3 Exchange-Specific Edge Cases

**Binance (BTC/USDT):**
- [ ] `LOT_SIZE` filter: quantity must be a multiple of `stepSize`
- [ ] `PRICE_FILTER`: price must be a multiple of `tickSize`
- [ ] `MIN_NOTIONAL`: quantity × price must exceed `minNotional`
- [ ] `MARKET_LOT_SIZE`: separate lot-size filter for market orders
- [ ] `MAX_NUM_ORDERS`: enforce open order count limit per symbol
- [ ] Handle `TRADING_PAUSED` status (symbol suspended): halt new orders, alert operator
- [ ] Handle `BREAK` order book state during volatile periods
- [ ] Futures-specific: funding rate payment timing awareness (every 8 hours)
- [ ] Futures-specific: liquidation price monitoring if leverage used (Stage 8+)

**Alpaca (SPY/QQQ/SOXX):**
- [ ] Pattern Day Trader (PDT) rule enforcement (< 25k account: max 3 round-trips per rolling 5 days)
- [ ] T+1 settlement-aware cash availability (PLAN.md: Settlement section)
- [ ] Extended-hours order type restrictions (limit orders only, no market orders)
- [ ] Halted symbol detection via Alpaca asset status endpoint
- [ ] Fractionable share support per symbol
- [ ] Market hours gate (pandas_market_calendars, PLAN.md: Market Session Management)

### 1.4 Rate-Limit and Ban Protection

- [ ] Per-endpoint rate limit tracking against Binance weight budget (1200 weight/minute default)
- [ ] Automatic backoff on HTTP 429 (respect `Retry-After` header)
- [ ] Hard stop on HTTP 418 (IP ban) — no retry, alert operator immediately
- [ ] WebSocket connection limit enforcement (Binance: max 5 streams per connection, max 1024 connections)
- [ ] Order rate limit: Binance enforces 10 orders/second, 100,000 orders/24h per account
- [ ] Circuit breaker: if 3 consecutive rate-limit errors within 60 seconds, pause for 5 minutes before retrying

### 1.5 Live Market Data Validation

- [ ] Real-time stale feed detection: alert if last tick age > configurable threshold (e.g., 5 seconds for crypto)
- [ ] Cross-source validation: primary WebSocket vs REST snapshot must agree within tolerance
- [ ] Order book quality checks: detect locked/crossed book, unreasonably wide spread
- [ ] Sequence gap detection: if sequence number gap > 0, trigger snapshot re-sync
- [ ] Price sanity check: reject tick if price deviates > N% from last valid tick (configurable per symbol)
- [ ] Volume anomaly detection: flag zero-volume ticks with non-zero price as suspicious

### 1.6 Real Fill Reconciliation

> **PLAN.md reference:** Reconciliation Edge Cases section (v4).

- [ ] Post-fill reconciliation: compare OMS fill record vs exchange trade history on every fill
- [ ] Scheduled reconciliation job: daily full position reconciliation at market close
- [ ] Discrepancy handling: if OMS position ≠ exchange position, halt new orders, alert operator
- [ ] Fill price reconciliation: expected fill price (order price) vs actual fill price — track slippage
- [ ] Partial fill tracking: partial fills accumulate into final fill record; reconcile at completion
- [ ] Commission reconciliation: expected fee (from TCA model) vs actual fee charged by exchange

### 1.7 API Permission Audits

- [ ] Monthly audit: verify trading key has only required permissions (no withdrawal permission on trading key)
- [ ] Alert on any unexpected permission change (compare against declared permission set in config)
- [ ] Document required minimum permissions per exchange in runbook
- [ ] Test that read-only key cannot submit orders (regression test for permission scope)

### 1.8 Sandbox → Micro-Live → Live Rollout Path

> **PLAN.md reference:** Stage 6, promotion pipeline (research → shadow → paper → micro-live → live).
> This section adds the operational gate checklist not consolidated elsewhere.

**Sandbox/Paper phase (minimum 30 days):**
- See Section 4 for full checklist.

**Micro-live phase ($10–$50 max order cap):**
- [ ] One strategy, one asset only (BTC/USDT first)
- [ ] Hard daily loss cap: $X (configured in YAML, enforced by risk engine)
- [ ] Hard weekly loss cap: $Y
- [ ] Manual daily approval before trading resumes each session
- [ ] Max single order size: $50 hard limit (configurable, enforced at order submission)
- [ ] Automatic rollback to paper mode if daily loss cap breached
- [ ] Operator receives Telegram alert on every live order submission
- [ ] Duration: minimum 14 days before considering promotion to full live
- [ ] All fills compared to paper fills — significant deviation halts promotion

**Full live phase:**
- [ ] Proven fill reconciliation (zero unexplained discrepancies in micro-live phase)
- [ ] Proven risk gate behavior (drawdown circuit breakers triggered correctly in micro-live)
- [ ] Proven alert routing (all alert types delivered correctly in micro-live)
- [ ] Proven operator kill switch (tested in micro-live under real conditions)
- [ ] Proven runbook completeness (no gap found during micro-live incidents)
- [ ] Capital increase: gradual only — no more than 2× capital per 30-day review cycle
- [ ] Capital increase requires: Sharpe above target, max drawdown below threshold, zero P0/P1 bugs

### 1.9 Real Exchange Incident Handling

- [ ] Runbook: `runbooks/exchange-api-degradation.md` — steps for partial exchange outage
- [ ] Runbook: `runbooks/exchange-full-outage.md` — steps for complete exchange unreachability
- [ ] Runbook: `runbooks/order-stuck-pending.md` — order submitted but no acknowledgement
- [ ] Runbook: `runbooks/position-mismatch.md` — OMS vs exchange position discrepancy
- [ ] Runbook: `runbooks/rate-limit-ban.md` — IP ban recovery procedure
- [ ] Runbook: `runbooks/fill-not-received.md` — fill not reflected in OMS despite exchange confirmation
- [ ] Each runbook: tested in staging/chaos drill before first live use

---

## 2. Operational Maturity

> **PLAN.md reference:** Stage 7 (Deployment & Infrastructure), Observability section, Chaos Engineering section.
> This section adds the operational processes that must exist beyond the technical implementation.

### 2.1 24/7 Monitoring Dashboard

- [ ] Grafana dashboard deployed in production environment (not just local dev)
- [ ] Dashboard panels: P&L (realtime), daily drawdown gauge, open positions, fill latency p99, feed staleness
- [ ] Dashboard panels: strategy signal count, order count, reconciliation status, feature flag states
- [ ] Dashboard panels: DB connection pool utilization, event bus queue depth, WebSocket reconnect count
- [ ] All Prometheus metrics (PLAN.md: Observability section) piped to production Grafana instance
- [ ] Dashboard access control: read-only for observers, write for operators
- [ ] Mobile-accessible dashboard for out-of-hours monitoring

### 2.2 Alert Routing Beyond Telegram

> **PLAN.md reference:** PagerDuty/Opsgenie noted in Stage 6 and Plugin Architecture section.

- [ ] Implement PagerDuty or Opsgenie integration as second alert channel (primary: Telegram)
- [ ] Alert severity routing:
  - `P0 (system down, uncontrolled loss)` → phone call escalation (PagerDuty/Opsgenie)
  - `P1 (risk gate tripped, reconciliation failure)` → Telegram + SMS
  - `P2 (feed staleness, elevated latency)` → Telegram only
  - `P3 (informational, daily summary)` → Telegram only
- [ ] Alert deduplication: suppress duplicate alerts for same root cause within 15-minute window
- [ ] Alert acknowledgement tracking: P0/P1 alerts must be acknowledged within 10 minutes or re-escalate
- [ ] Alert runbook URL in every P0/P1 alert body (PLAN.md: "runbook URL in every error log")
- [ ] Dead man's switch: if system produces zero heartbeat events for > 5 minutes → P0 alert

### 2.3 Scheduled Disaster Recovery Drills

- [ ] Monthly: full backup restore rehearsal (restore to staging, verify data integrity)
- [ ] Quarterly: full-system chaos drill (PLAN.md: Chaos Engineering, game day exercises)
- [ ] Quarterly: exchange outage simulation (test fallback behavior and operator response)
- [ ] Semi-annual: complete system rebuild from scratch using documented runbooks only
- [ ] Each drill: result documented in `docs/post_mortems/` with action items
- [ ] Drill calendar: scheduled in advance, operator availability confirmed

### 2.4 Backup Restore Rehearsals

- [ ] Automated daily backups: Postgres dump + Parquet raw data + config snapshots
- [ ] Backup integrity check: automated restore to staging and verify row counts weekly
- [ ] RPO target: < 1 hour (maximum acceptable data loss)
- [ ] RTO target: < 4 hours (maximum time to restore to operational state)
- [ ] Documented restore procedure: `runbooks/disaster-recovery.md`
- [ ] Restore procedure tested by a person who was not the original author (bus factor check)

### 2.5 Incident Post-Mortem Workflow

- [ ] Every P0/P1 incident triggers a blameless post-mortem within 48 hours
- [ ] Post-mortem template: `docs/post_mortems/_template.md` (PLAN.md: post-mortem archive)
- [ ] Post-mortem sections: timeline, root cause, contributing factors, action items, owner, due date
- [ ] Action items tracked to completion — not just written and forgotten
- [ ] Post-mortem review: all post-mortems reviewed before next micro-live → live promotion
- [ ] Post-mortem archive: searchable, tagged by component and severity

### 2.6 Operator Roles and Access Control

- [ ] Define operator roles: `viewer`, `operator`, `admin`
- [ ] `viewer`: read-only dashboard, no kill switch, no config change
- [ ] `operator`: can trigger kill switch, can approve/reject daily trading session, cannot change config
- [ ] `admin`: full access, config changes require second admin approval
- [ ] Operator console (PLAN.md: Stage 7 operator console) enforces these roles
- [ ] All operator actions logged to audit trail with actor identity
- [ ] Role assignments versioned in config, changes require PR review

### 2.7 Deployment Rollback Automation

- [ ] Git tag on every production deployment
- [ ] One-command rollback: `make rollback VERSION=<tag>` restores previous image + config
- [ ] Rollback tested in staging before each production deployment
- [ ] Rollback runbook: `runbooks/deployment-rollback.md`
- [ ] Automatic rollback trigger: if P0 alert fires within 10 minutes of deployment → automatic rollback + alert

### 2.8 Security Rotation Drills

- [ ] Quarterly: simulate API key compromise — rotate all keys, verify zero-downtime, document time taken
- [ ] Quarterly: simulate DB credential leak — rotate, verify, test restore
- [ ] Annual: full security posture review (dependency audit, permission audit, secret scanner sweep)
- [ ] Post-drill report: time to detect, time to rotate, gaps found
- [ ] Drill calendar: scheduled, operator-attended

### 2.9 Production SLO Reviews

> **PLAN.md reference:** Observability section defines SLO definitions and error budget tracking.

- [ ] Monthly SLO review: actual vs target for all defined SLOs
- [ ] SLOs defined per component: data feed freshness, order submit latency p99, reconciliation completeness
- [ ] Error budget burn rate alert: if error budget > 50% consumed by mid-month → P1 alert
- [ ] SLO review outcome: documented, action items assigned
- [ ] SLO thresholds revisited annually or after major architecture change

### 2.10 Operator Handoff and Runbook Procedures

- [ ] Session handoff protocol: outgoing operator documents open positions, active alerts, pending actions
- [ ] Handoff template: `runbooks/operator-handoff.md`
- [ ] No unattended live trading session > 8 hours without documented handoff
- [ ] On-call rotation documented and tested before first live trading day
- [ ] Escalation contact list: up to date, tested (phone numbers working) quarterly

---

## 3. Quant Maturity

> **PLAN.md reference:** Stage 3 (Strategy Engine), Stage 4 (Backtesting), Stage 8 (Quant & AI Expansion),
> promotion pipeline, stress testing, risk decomposition sections.
> This section adds the forward-looking quantitative rigor that builds on the existing infrastructure.

### 3.1 New Strategies Only Through the Promotion Pipeline

> **PLAN.md reference:** promotion stages (research → shadow → paper → micro-live → live), ADR-0007.

- [ ] No strategy may skip a promotion stage — gate criteria must be documented and met
- [ ] Each strategy has a one-pager: `docs/strategies/<name>.md` — hypothesis, edge, regime, known risks
- [ ] Strategy one-pager signed off before shadow phase begins
- [ ] Automated gate enforcement: promotion pipeline code rejects advancement if gate metrics not met

### 3.2 Portfolio Optimizer

- [ ] Mean-variance optimization (Markowitz, with shrinkage estimators for small sample bias)
- [ ] Alternative: risk parity (equal risk contribution per strategy/asset)
- [ ] Alternative: Black-Litterman (blend market equilibrium with view forecasts)
- [ ] Optimizer runs offline (not in the hot path) — output fed as static allocation to risk engine
- [ ] Rebalancing cadence: weekly with audit log entry per rebalance decision
- [ ] Optimizer output versioned: each optimization run produces a signed config snapshot

### 3.3 Correlation-Aware Capital Allocation

- [ ] Real-time correlation matrix computed from rolling 30/60/90-day returns
- [ ] Alert if strategy correlation > threshold (e.g., two "independent" strategies become correlated)
- [ ] Capital allocation accounts for correlation: correlated strategies share a combined capital bucket
- [ ] Correlation matrix updated at least daily; stored for historical analysis
- [ ] Stress correlation: assume correlation → 1.0 under crash scenarios (PLAN.md: Stress Testing)

### 3.4 Regime-Specific Strategy Weights

- [ ] Regime detector: classify market state (trending, mean-reverting, high-vol, low-vol, risk-off)
- [ ] Strategy registry maps strategies to regimes: which strategy performs in which regime
- [ ] Capital weight adjusted per regime classification — automated, not manual
- [ ] Regime transitions logged with audit entry (old regime, new regime, timestamp, trigger)
- [ ] Regime detector must have its own backtested accuracy metric before use in production

### 3.5 Walk-Forward Automation

> **PLAN.md reference:** Stage 4 mentions walk-forward analysis.

- [ ] Automated walk-forward: scheduled monthly refit of strategy parameters on expanding window
- [ ] Walk-forward results compared to in-sample results: flag excessive degradation
- [ ] Parameter stability check: if optimal parameters shift dramatically each period → strategy flagged for review
- [ ] Walk-forward automation integrated with promotion pipeline: required before micro-live promotion
- [ ] Results stored in research database with reproducible seeds (PLAN.md: deterministic replay)

### 3.6 Signal Decay Detection

- [ ] Per-strategy signal decay monitor: rolling IC (information coefficient) over last N periods
- [ ] Alert if IC drops below threshold sustained for K periods
- [ ] Automatic strategy demotion trigger: if signal decay confirmed → strategy moved to shadow mode
- [ ] Signal decay report: weekly summary across all active strategies
- [ ] Root cause investigation procedure documented in `runbooks/strategy-signal-decay.md`

### 3.7 Stress Testing

> **PLAN.md reference:** Stress Testing & Historical Scenario Replay section (v5).

- [ ] Run full stress test suite on every new strategy before promotion (PLAN.md scenarios)
- [ ] Run quarterly on all live strategies
- [ ] Add new scenarios after each major market event
- [ ] Stress test failure (loss > threshold in scenario) blocks promotion — requires architecture review

### 3.8 Live Alpha Attribution

- [ ] Per-strategy realized P&L decomposed: market beta, strategy alpha, factor exposure
- [ ] Attribution computed weekly; stored in database for trend analysis
- [ ] Alert if alpha decays while factor exposure increases (strategy "becoming beta")
- [ ] Attribution report available in operator dashboard
- [ ] Attribution methodology documented: `docs/strategies/attribution_methodology.md`

### 3.9 Transaction Cost Model Calibration from Real Fills

> **PLAN.md reference:** TCA module referenced in Stage 5+, compliance/ and tca/ directories.

- [ ] Pre-trade TCA model: estimate expected cost (spread + commission + market impact) before order submission
- [ ] Post-trade calibration: compare pre-trade estimate vs actual fill cost on every trade
- [ ] Calibration runs monthly: update model parameters (spread model, market impact model coefficients)
- [ ] Slippage budget per strategy: if actual slippage consistently exceeds budget → strategy review
- [ ] TCA calibration report: monthly, stored alongside strategy performance reports

### 3.10 Strategy Retirement and Demotion Policy

- [ ] Formal demotion criteria: sustained Sharpe below threshold OR signal decay confirmed OR stress test failure
- [ ] Demotion procedure: `runbooks/strategy-demotion.md`
  1. Move strategy to shadow mode
  2. Close all open positions gracefully (no forced liquidation)
  3. Archive strategy config with retirement date and reason
  4. Post-mortem: why did the edge decay?
- [ ] Strategy graveyard: `docs/strategies/retired/` — keeps retired strategies for reference
- [ ] No silent retirement: every retirement has a documented rationale

### 3.11 Capital Scaling Rules Based on Evidence

- [ ] Capital may only increase after a completed review cycle meeting all thresholds:
  - [ ] Sharpe > target (rolling 30 days)
  - [ ] Max drawdown < threshold (rolling 30 days)
  - [ ] Positive alpha attribution (rolling 30 days)
  - [ ] Zero P0/P1 incidents in the period
  - [ ] Reconciliation 100% clean
- [ ] Maximum capital increase per cycle: 2× (no exceptions)
- [ ] Capital decrease triggers: drawdown breach → automatic reduction to last safe level
- [ ] Capital scaling log: every increase/decrease recorded with evidence snapshot

---

## 4. Real-Money Rollout Sequence

> This is the gate checklist that governs the transition from paper to real money.
> Every checkbox must be verifiably completed. No partial credit.

### Gate 0: Paper Readiness (Before Micro-Live)

**Applies to both tracks: BTC/USDT (Binance) and ETFs (Alpaca: SPY/QQQ/SOXX/IBIT)**

**BTC/USDT track:**
- [ ] Minimum 30 calendar days of paper trading completed
- [ ] Minimum 100 completed round-trip trades (not just elapsed time)
- [ ] No single-day paper P&L deviation > 2× expected from backtest
- [ ] Reconciliation clean: OMS position = paper exchange position for all 30 days
- [ ] Max paper drawdown within backtest-predicted range (no unexpected behavior)
- [ ] Paper/backtest parity check: replay same signal period through backtest, compare outputs

**ETF track (SPY/QQQ/SOXX/IBIT via Alpaca paper):**
- [ ] Alpaca paper credentials configured and health check passing (`trading-bot-etf paper-execution-test`)
- [ ] Minimum 30 calendar days of Alpaca paper trading completed
- [ ] Minimum 50 completed round-trip trades across all 4 ETF symbols
- [ ] `trading-bot-etf test-synthetic` passes for all 4 symbols (≥5 cycles each)
- [ ] `trading-bot-etf backtest` run for full year — results within expected range
- [ ] No single-day ETF paper P&L deviation > 2× backtest expectation
- [ ] Reconciliation clean: OMS ETF positions = Alpaca paper positions for all 30 days
- [ ] Market hours gate verified: no order attempts outside NYSE 09:30–16:00 ET
- [ ] NYSE holiday handling verified: no order attempts on market holidays
- [ ] PDT rule awareness documented (< $25k account: max 3 round-trips per rolling 5 days)

**Shared (both tracks):**
- [ ] All runbooks written: at minimum those listed in Section 1.9 above
- [ ] Chaos drill completed: at least one planned failure injection in staging
- [ ] Post-mortem from chaos drill: action items resolved
- [ ] Kill switch tested: operator can halt system within 60 seconds from Telegram
- [ ] Alert routing tested: all alert types (P0 through P3) delivered to correct channels
- [ ] Operator on-call rotation established and documented

### Gate 1: Shadow / Live Market Observation (Parallel to Paper)

**BTC/USDT (Binance):**
- [ ] System connected to real market data WebSocket (not sandbox feed)
- [ ] All data validation rules running against real tick data
- [ ] Latency measured: signal-to-order-submission latency under real market conditions
- [ ] Order book quality checks validated against real order book
- [ ] No order submission — observation only
- [ ] Duration: minimum 7 days of live market observation before micro-live

**ETF (Alpaca):**
- [ ] Alpaca real-time market data feed active (not paper feed)
- [ ] Signal generation verified on live ETF data (SMA + RSI signals logged, no orders)
- [ ] Market hours guard verified in live session: system correctly detects open/close
- [ ] Duration: minimum 5 trading days of live ETF observation before micro-live

### Gate 2: Micro-Live Start — BTC/USDT (Phase A)

> Start with BTC/USDT. ETF micro-live begins only after Phase A passes.

- [ ] One strategy only (chosen by operator, documented in audit log)
- [ ] One asset only: BTC/USDT
- [ ] Max single order: $50 hard limit (enforced in risk engine, not configurable at runtime)
- [ ] Daily loss cap: configured and tested (triggers automatic halt)
- [ ] Weekly loss cap: configured and tested
- [ ] Manual daily approval: operator must explicitly enable each trading session
- [ ] Operator receives alert on every order submission
- [ ] Automatic rollback to paper: if daily loss cap hit → system switches to paper mode, alerts operator
- [ ] Duration: minimum 14 calendar days

### Gate 2b: Micro-Live Start — ETF (Phase B, after Gate 2 passes)

> Begin ETF micro-live only after BTC/USDT micro-live (Gate 2) completes successfully.

- [ ] Gate 2 (BTC/USDT) fully passed and documented
- [ ] Start with SPY only (most liquid, lowest volatility of the four)
- [ ] Max single ETF order: $100 hard limit (Alpaca commission-free, higher limit acceptable)
- [ ] Daily ETF loss cap: configured and tested
- [ ] Market hours guard active: orders blocked outside NYSE hours
- [ ] PDT rule guard active: round-trip counter tracked per rolling 5-day window
- [ ] Operator receives alert on every ETF order submission
- [ ] Duration: minimum 10 trading days on SPY before expanding to QQQ
- [ ] Expand to QQQ: minimum 5 trading days before adding SOXX
- [ ] Expand to SOXX: minimum 5 trading days before adding IBIT
- [ ] IBIT last: highest volatility — minimum 10 trading days standalone before full portfolio

### Gate 3: Micro-Live → Full Live

**BTC/USDT track:**
- [ ] 14+ days micro-live completed
- [ ] Zero unexplained fill discrepancies in micro-live phase
- [ ] Risk gates triggered correctly in micro-live
- [ ] All micro-live fills compared to paper fills: slippage within modeled range
- [ ] All micro-live alerts delivered correctly
- [ ] Operator kill switch exercised at least once during micro-live phase
- [ ] Runbooks: no gap found during micro-live
- [ ] Post-mortems from any micro-live incidents: reviewed and closed

**ETF track (all 4 symbols — SPY/QQQ/SOXX/IBIT):**
- [ ] Gate 2b fully completed for all 4 symbols
- [ ] Zero unexplained Alpaca fill discrepancies across all ETF symbols
- [ ] T+1 settlement tracking verified: no over-allocation of unsettled cash
- [ ] PDT rule: no violation in micro-live phase
- [ ] Slippage for each ETF within backtest-predicted range
- [ ] Market hours guard: zero out-of-hours order attempts logged
- [ ] ETF-specific runbooks written and tested: halt detection, PDT breach, market close handling
- [ ] Post-mortems from any ETF micro-live incidents: reviewed and closed

**Capital (both tracks):**
- [ ] Capital increase: start at minimum viable amount (operator decision, documented)
- [ ] Capital scaling only after full evidence cycle (Section 3.11)
- [ ] ETF capital allocation: respect `max_capital_pct` per symbol from `asset_universe.yaml`

### Rollback Triggers (Automatic)

At any live stage, these trigger automatic rollback to paper mode:

- Daily loss cap breached
- Reconciliation discrepancy detected > threshold
- Feed staleness > 60 seconds on primary data source
- Risk engine error (any unhandled exception in risk path)
- DB connection failure > 30 seconds

At any live stage, these trigger operator alert + manual decision required:

- Any P0 alert
- Reconciliation discrepancy < threshold but non-zero
- Slippage > 2× modeled estimate on 3 consecutive trades

---

## 5. Calibration and Evidence

> The final stage of production confidence is not code — it is evidence.
> Evidence means measured, documented, reproducible proof that the system behaves as designed.

### 5.1 Expected vs Realized Slippage

- [ ] For every trade: record expected slippage (pre-trade TCA estimate) and actual slippage (fill price vs mid price at signal time)
- [ ] Weekly calibration report: mean, median, p95 slippage per strategy per symbol
- [ ] Alert: if actual slippage > 2× model estimate on weekly aggregate → TCA model recalibration required
- [ ] TCA model recalibration: monthly, using last 30 days of real fill data
- [ ] Calibration history stored: enables trend analysis (is market impact growing over time?)

### 5.2 Fill Quality Measurement

- [ ] Fill quality metrics computed per trade: fill ratio, avg fill price vs VWAP, time-to-fill
- [ ] Poor fill quality definition: fill price > N bps from arrival mid (configurable per symbol)
- [ ] Persistent poor fill quality → review order type (market → limit with aggressor flag)
- [ ] Fill quality report: weekly, available in operator dashboard
- [ ] Fill quality degradation trend → runbook: `runbooks/fill-quality-degradation.md`

### 5.3 Live Latency Verification

- [ ] Measure and record end-to-end latency: signal generation → order submission → first fill ack
- [ ] Compare to latency budget defined in PLAN.md (signal-to-fill latency SLO)
- [ ] Alert if p99 latency exceeds budget for 3 consecutive measurement periods
- [ ] Latency breakdown: signal computation, risk check, order formatting, network RTT to exchange, order processing
- [ ] Network RTT to exchange: tested and documented at deployment (colocation vs cloud)

### 5.4 Strategy Behavior Validation Across Regimes

- [ ] For each strategy: define expected behavior per market regime (trending, mean-reverting, high-vol, risk-off)
- [ ] Live behavior comparison: does strategy behave as the regime hypothesis predicted?
- [ ] Regime mismatch → investigation report: why does behavior differ from hypothesis?
- [ ] Regime validation cadence: quarterly review for each live strategy
- [ ] Regime hypothesis updated when evidence contradicts original assumption

### 5.5 Incident Response Validation

- [ ] Prove kill switch works: every 30 days, test kill switch in staging with live-equivalent conditions
- [ ] Prove alert routing works: monthly test alert through full chain (P0 path must reach operator within 2 minutes)
- [ ] Prove escalation works: quarterly, simulate missed alert — PagerDuty/Opsgenie escalation fires within timeout
- [ ] Prove operator actions are safe: every operator command in the console must be idempotent — double-execution produces same outcome
- [ ] Drill results: documented in `docs/post_mortems/drills/`

### 5.6 Restore Process Validation

- [ ] Monthly: restore from backup to staging, verify OMS state matches last audit log entry
- [ ] Quarterly: full system restore from scratch — database, config, raw data, replay engine
- [ ] Restore time measured and compared to RTO target (< 4 hours)
- [ ] Any restore that exceeds RTO → incident investigation + runbook update
- [ ] Restore drill attended by at least one operator who was not the author of the restore procedure

### 5.7 Audit Replay Validation

- [ ] Quarterly: replay last 30 days of audit log through replay engine — verify outputs match stored state
- [ ] Replay discrepancy = P0 incident (audit integrity failure)
- [ ] Hash chain verification: run hash chain validator against full audit log monthly
- [ ] If hash chain breaks: identify first broken link, investigate, document, notify operator

### 5.8 Safety Gate Bypass Proof

- [ ] Property-based test suite (Hypothesis): proves no combination of inputs bypasses the risk engine
- [ ] Mutation testing (mutmut, PLAN.md): proves test suite catches risk logic regressions
- [ ] Penetration test: attempt to submit a live order through every non-standard code path — verify all paths hit the risk engine
- [ ] Static analysis: verify no code path reaches `place_order()` without passing through `RiskEngine.evaluate()`
- [ ] This test suite runs in CI on every commit to main

---

## Implementation Notes

- **Do not start Section 1–5 work until PLAN.md Stages 0–8 are complete and verified.**
- **Do not enable `live_trading_enabled = true` until Gate 3 (Section 4) is fully checked.**
- **Each checklist item becomes a GitHub issue when work begins** — not before.
- **ADRs required for:** production secrets provider choice, portfolio optimizer algorithm choice, alert routing architecture.
- **Runbooks required for:** every incident type in Section 1.9, strategy demotion (Section 3.10), operator handoff (Section 2.10), all runbooks in Section 2.

## Related Documents

- `docs/PLAN.md` — full development specification (Stages 0–8)
- `trading_bot/docs/adr/` — Architecture Decision Records
- `trading_bot/docs/runbooks/` — Operational runbooks (to be expanded per this document)
- `trading_bot/docs/post_mortems/` — Post-mortem archive
- `trading_bot/docs/strategies/` — Strategy one-pagers

---

*This document is a living backlog. Update it as evidence accumulates and gates pass.*  
*Last updated: 2026-05-11*
