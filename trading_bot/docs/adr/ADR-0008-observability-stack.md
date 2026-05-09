# ADR-0008: Observability Stack — OpenTelemetry + Prometheus + structlog

**Status:** Accepted
**Date:** 2024-01-01
**Deciders:** Architecture team

---

## Context

Observability is not optional in a trading system. Without it:
- You cannot debug production incidents (only have logs from before the crash)
- You cannot detect strategy decay before it shows up in P&L
- You cannot prove to an auditor that the system behaved correctly
- You cannot optimize performance (optimize what you cannot measure)

The three pillars of observability are: logs, metrics, and traces.

---

## Decision

**Three-pillar observability from Stage 0:**

### Logging: structlog
- JSON format in production (parseable by Loki/ELK)
- Correlation ID injected into every log entry via ContextVar
- Runbook URL embedded in every ERROR/CRITICAL log
- No print() anywhere in production code

### Metrics: Prometheus
- prometheus-client with /metrics HTTP endpoint
- Key metrics defined in Stage 0 (see metrics.py)
- Grafana dashboards in Stage 7
- SLO definitions with error budget tracking

### Tracing: OpenTelemetry
- Signal-to-fill spans: end-to-end latency for every order
- Console exporter in development, OTLP → Jaeger/Tempo in production
- Sampling policy: 100% for orders, 10% for data fetch
- Correlation ID propagated as trace ID for log-trace correlation

---

## Consequences

### Positive

- Replay-driven debugging: trace ID in logs → find exact trace in Jaeger
- P99 latency metrics → detect strategy performance degradation
- All three pillars use standard protocols (OpenTelemetry, Prometheus)

### Negative

- Three separate systems to configure and maintain
- OpenTelemetry adds ~5ms overhead per span (acceptable)

### Risks

- Log aggregation (Loki) is Stage 7 — until then, logs are local files
- Prometheus data is not durable by default — add remote_write in Stage 7

---

## Alternatives Considered

| Option | Reason Rejected |
|--------|-----------------|
| logging (stdlib) only | No correlation IDs, no structured fields, not searchable |
| Datadog | Expensive, vendor lock-in |
| New Relic | Same as Datadog |
| OpenSearch only | No metrics, no traces — only logs |

---

## References

- OpenTelemetry: https://opentelemetry.io/
- Prometheus: https://prometheus.io/
- structlog: https://www.structlog.org/
- Google SRE Book: https://sre.google/sre-book/monitoring-distributed-systems/
