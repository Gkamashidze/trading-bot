# ADR-0001: Event Bus Choice — asyncio.Queue vs Redis Streams vs Kafka

**Status:** Accepted
**Date:** 2024-01-01
**Deciders:** Architecture team

---

## Context

The trading bot requires a centralized event bus for decoupled communication
between subsystems: market data → signal engine → risk engine → execution.

The event bus must support:
- Pub/sub with multiple consumers per event type
- Backpressure (slow consumer signals producer)
- Persistence for replay (at minimum in production)
- Low latency (< 1ms intra-process)

---

## Decision

**Stage 0/1: asyncio.Queue (in-process)**

A bounded asyncio.Queue per consumer. Simple, zero infrastructure, zero ops.
Replay is supported via the Postgres audit log + file-based fixtures.

**Stage 2+: upgrade to Redis Streams**

When WebSocket streams are added (Stage 2) and we need durable pub/sub
across process restarts, migrate to Redis Streams. This also enables
consumer groups and message acknowledgement.

**Stage 6+ (optional): Kafka**

Only if event throughput exceeds ~10k events/second — unlikely for Stage 0-5.
Kafka adds significant operational complexity; we avoid it until necessary.

---

## Consequences

### Positive

- Zero infrastructure in Stage 0 — just Python
- asyncio.Queue is trivially testable (no network)
- Upgrade path is explicit (Stage 2 → Redis)

### Negative

- Events are lost on process restart in Stage 0 (acceptable — replay uses audit log)
- Single-process only in Stage 0 (acceptable — multi-process in Stage 6+)

### Risks

- asyncio.Queue.put() can block if queue is full → use put_nowait() with explicit overflow policy

---

## Alternatives Considered

| Option | Reason Rejected |
|--------|-----------------|
| Redis Streams from Stage 0 | Requires Redis infra before we have any strategies — premature |
| Kafka from Stage 0 | Massive operational overhead for Stage 0 infrastructure |
| In-memory pub/sub library (PyPubSub) | Less composable, harder to test, no upgrade path |

---

## References

- Redis Streams: https://redis.io/docs/data-types/streams/
- asyncio.Queue: https://docs.python.org/3/library/asyncio-queue.html
