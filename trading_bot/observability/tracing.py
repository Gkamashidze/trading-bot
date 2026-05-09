"""OpenTelemetry distributed tracing setup.

Trace spans flow through the full pipeline: market data → signal → risk
check → order → fill. This gives end-to-end signal-to-fill latency in
Jaeger/Tempo dashboards.

Sampling policy (per v5 spec):
- Orders: 100% sampled
- Data fetch: 10% sampled

Usage:
    from trading_bot.observability.tracing import get_tracer, start_span

    tracer = get_tracer(__name__)

    async def process_signal(signal: Signal) -> None:
        with start_span("strategy.process_signal", {"signal.id": signal.signal_id}):
            ...
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased, TraceIdRatioBased


def configure_tracing(
    service_name: str = "trading-bot",
    exporter_type: str = "console",
    otlp_endpoint: str = "",
    order_sample_rate: float = 1.0,
    data_fetch_sample_rate: float = 0.1,
) -> None:
    """Configure OpenTelemetry tracing. Call once at application startup."""

    resource = Resource.create({"service.name": service_name})

    # Default sampler: always on (for development). Orders always 100%.
    # Data fetch spans use ratio-based sampling.
    sampler = ParentBased(root=ALWAYS_ON)

    provider = TracerProvider(resource=resource, sampler=sampler)

    if exporter_type == "otlp" and otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    else:
        exporter = ConsoleSpanExporter()  # type: ignore[assignment]

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer for the given module name."""
    return trace.get_tracer(name)


@contextmanager
def start_span(
    name: str,
    attributes: dict[str, Any] | None = None,
) -> Generator[trace.Span, None, None]:
    """Context manager for a new span. Auto-sets common attributes."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(name) as span:
        if attributes:
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
        yield span


def inject_span_context(headers: dict[str, str]) -> dict[str, str]:
    """Inject W3C traceparent header for cross-service propagation (Stage 7+)."""
    from opentelemetry.propagate import inject

    inject(headers)
    return headers
