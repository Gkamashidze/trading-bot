# ADR-0005: Idempotency Key Strategy — UUID v7 + Postgres Store

**Status:** Accepted
**Date:** 2024-01-01
**Deciders:** Architecture team

---

## Context

Trading systems are subject to crash recovery and retry scenarios. Without
idempotency, a crash between "order submitted" and "receipt logged" can lead to:
- Duplicate order submissions (buying twice at wrong price)
- Phantom positions (OMS shows position, exchange doesn't)
- Double-fee charges
- Incorrect portfolio state after recovery

Every state-changing operation must be idempotent: re-running with the same
parameters must produce the same outcome, not a duplicate side effect.

---

## Decision

**UUID v7 for key generation + Postgres-backed store**

- **UUID v7**: time-ordered (monotonically increasing by millisecond).
  Better than UUID v4 for trading: keys sort chronologically, making
  debugging much easier ("what orders were placed in the last 5 minutes?")

- **Postgres store**: `idempotency_keys` table with TTL column.
  INSERT ON CONFLICT DO NOTHING provides atomic first-writer wins semantics.

- **7-day TTL**: keys expire after 7 days. This is intentionally longer than
  any expected retry window.

- **@idempotent decorator**: all state-changing functions decorated with
  `@idempotent(key_func=...)` to enforce the contract at compile time.

---

## Consequences

### Positive

- Crash recovery is safe: retrying any operation is harmless
- Duplicate order detection at the code level (not just exchange-side)
- UUID v7 keys are debuggable (chronological ordering)
- Audit log captures all idempotency hits for post-mortem analysis

### Negative

- Postgres roundtrip on every state-changing operation (< 1ms acceptable)
- Keys must be passed through the call chain (adds parameter)

### Risks

- If Postgres is down, idempotency store is unavailable → fail-safe: block
  all state-changing operations until DB is reachable
- Key collision on UUID v7: statistically impossible (128-bit + ms timestamp)

---

## Alternatives Considered

| Option | Reason Rejected |
|--------|-----------------|
| Redis store | Extra infrastructure in Stage 0; Postgres already required |
| UUID v4 | Random — not time-ordered, harder to debug |
| ULID | Less library support, similar properties to UUID v7 |
| Application-layer counter | Not globally unique, distributed collision risk |

---

## References

- UUID v7 spec: https://www.ietf.org/archive/id/draft-peabody-dispatch-new-uuid-format-04.txt
- Idempotency keys (Stripe): https://stripe.com/docs/idempotency
