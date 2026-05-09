"""Observability: structured logging, tracing, and metrics.

All three pillars live here. Import from this package rather than from
structlog/opentelemetry/prometheus directly — this lets us swap backends
without touching business logic.
"""
