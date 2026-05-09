# ADR-0007: Strategy Promotion Pipeline — research → shadow → paper → micro-live → live

**Status:** Accepted
**Date:** 2024-01-01
**Deciders:** Architecture team

---

## Context

Deploying an unvalidated strategy directly to live trading is gambling.
Even a strategy that looks excellent in backtests can fail in production
due to: overfitting, data snooping bias, regime change, execution costs,
or simply implementation bugs.

An institutional trading desk never deploys directly. They use a formal
validation pipeline where a strategy must pass gates at each stage.

---

## Decision

**Five-stage promotion pipeline with mandatory gates:**

### Stage 1: Research
- In Jupyter notebooks only (NEVER imported by production)
- Hypothesis documented before testing (prevents p-hacking)
- Walk-forward validation + deflated Sharpe ratio check
- Peer review required before promotion

### Stage 2: Shadow (minimum 5 days)
- Strategy runs in production code but produces signals only (no orders)
- Signal determinism verified: same data → same signal every time
- Zero crashes required
- Gate: hypothesis documented, code review passed, 5 days clean signals

### Stage 3: Paper (minimum 10 days)
- Orders submitted to paper trading account (Alpaca Paper / Binance Testnet)
- Full reconciliation cycle active
- Runbook written for top 3 failure modes
- Gate: Sharpe > threshold, drawdown < limit, 7 days clean reconciliation

### Stage 4: Micro-Live (minimum 14 days, $100-$1000 capital cap)
- Real money, strictly capped capital
- All safety systems active
- Gate: 14 days, Sharpe > threshold, drawdown < limit, zero P0/P1 bugs,
  post-mortems reviewed for any incidents

### Stage 5: Live
- Capital scaling: 5% → 25% → 50% → 100% of allocation
- Weekly performance review
- Retirement criteria defined

**Rollback:** live → paper instantly via feature flag.

---

## Consequences

### Positive

- Bugs are caught in shadow/paper before they cost real money
- Promotion gates create a paper trail (compliance, post-mortem)
- Rollback is instant (feature flag)
- Capital at risk grows gradually (5% canary)

### Negative

- Slower to live trading than "YOLO deploy"
- Requires paper trading accounts on all exchanges
- Shadow + paper = 15 days minimum before micro-live

### Risks

- Teams under pressure may want to skip stages — this is explicitly prohibited
- Paper trading slippage ≠ live slippage (still a risk at micro-live gate)

---

## Alternatives Considered

| Option | Reason Rejected |
|--------|-----------------|
| Research → Live directly | Unacceptable risk |
| Research → Paper → Live | Misses shadow stage (implementation bugs) |
| No capital cap at micro-live | No meaningful risk limit |

---

## References

- Lopez de Prado "Advances in Financial Machine Learning" — Ch. 11 (Feature Importance)
- Deflated Sharpe Ratio: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
