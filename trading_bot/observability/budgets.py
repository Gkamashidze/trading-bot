"""Performance budget enforcement.

Each subsystem declares a latency SLO in BUDGETS_MS. Wrap latency-sensitive
code with the `budget()` async context manager — violations are logged as
warnings and tracked in a Prometheus counter so alerts can fire automatically.

Usage:
    async with budget("risk_check"):
        decision = risk_engine.pre_trade_check(order, snapshot, price)

    # Or override the budget inline:
    async with budget("order_submit", budget_ms=300.0):
        await exchange.place_order(req)
"""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from prometheus_client import Counter

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_BUDGET_VIOLATIONS = Counter(
    "trading_performance_budget_violations_total",
    "Number of times a subsystem exceeded its latency SLO",
    labelnames=["subsystem"],
)

# Documented SLOs per subsystem (milliseconds).
# These are the budgets — not hard limits. Violations are logged, not raised.
BUDGETS_MS: dict[str, float] = {
    "risk_check": 5.0,
    "signal_generation": 50.0,
    "signal_to_order": 50.0,
    "order_submit": 200.0,
    "reconciliation": 5_000.0,
    "data_validation": 100.0,
    "websocket_tick_processing": 10.0,
}


@asynccontextmanager
async def budget(
    subsystem: str,
    budget_ms: float | None = None,
) -> AsyncGenerator[None, None]:
    """Async context manager that enforces a latency budget.

    Falls back to BUDGETS_MS[subsystem] if budget_ms is not provided.
    If the subsystem is unknown and no budget_ms given, timing is recorded
    without a limit check (debug log only).
    """
    limit = budget_ms if budget_ms is not None else BUDGETS_MS.get(subsystem)
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        if limit is not None and elapsed_ms > limit:
            _BUDGET_VIOLATIONS.labels(subsystem=subsystem).inc()
            log.warning(
                "performance_budget_exceeded",
                subsystem=subsystem,
                elapsed_ms=round(elapsed_ms, 3),
                budget_ms=limit,
                overage_ms=round(elapsed_ms - limit, 3),
            )
        else:
            log.debug(
                "performance_budget_ok",
                subsystem=subsystem,
                elapsed_ms=round(elapsed_ms, 3),
                budget_ms=limit,
            )
