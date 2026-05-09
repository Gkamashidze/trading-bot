"""Domain event definitions for the centralized event bus.

Events are the lingua franca of the system. Every subsystem communicates
via events — never via direct function calls across module boundaries.
This enables replayability: record the event stream, replay it, get
identical system behaviour.

Event schema is versioned. Old events must be replayable forever.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from trading_bot.core.models import (
    ExchangeId,
    OHLCVBar,
    OrderRequest,
    OrderState,
    PortfolioSnapshot,
    Signal,
)


class _BaseEvent(BaseModel):
    """Common fields for all domain events."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str
    schema_version: str = "1.0"
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    # Hash chain — filled by the audit log writer
    prev_event_hash: str | None = None
    event_hash: str | None = None

    # Config snapshot — for replay correctness
    config_snapshot: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Market Data Events
# ---------------------------------------------------------------------------


class MarketEvent(_BaseEvent):
    """New OHLCV bar arrived from a data source."""

    event_type: str = "market.ohlcv"
    bar: OHLCVBar


class TickerEvent(_BaseEvent):
    """Real-time bid/ask update."""

    event_type: str = "market.ticker"
    symbol: str
    exchange: ExchangeId
    bid: str
    ask: str
    timestamp: datetime


class DataStalenessEvent(_BaseEvent):
    """Data feed has not updated within the expected freshness window."""

    event_type: str = "market.staleness"
    symbol: str
    exchange: ExchangeId
    last_update: datetime
    staleness_seconds: float


# ---------------------------------------------------------------------------
# Signal Events
# ---------------------------------------------------------------------------


class SignalEvent(_BaseEvent):
    """Strategy emitted a trading signal."""

    event_type: str = "strategy.signal"
    signal: Signal


# ---------------------------------------------------------------------------
# Risk Events
# ---------------------------------------------------------------------------


class RiskEvent(_BaseEvent):
    """Risk engine evaluated a signal."""

    event_type: str = "risk.evaluation"
    signal_id: str
    accepted: bool
    reason: str
    drawdown_pct: float
    tier: int | None = None  # which circuit breaker tier, if triggered


class DrawdownBreachEvent(_BaseEvent):
    """A drawdown circuit breaker tier was breached."""

    event_type: str = "risk.drawdown_breach"
    tier: int
    drawdown_pct: float
    action: str  # "pause_new" | "full_halt" | "emergency_liquidate"


# ---------------------------------------------------------------------------
# Order / Execution Events
# ---------------------------------------------------------------------------


class PreTradeCheckEvent(_BaseEvent):
    """Pre-trade checks (compliance, risk, funds, idempotency) ran."""

    event_type: str = "execution.pre_trade_check"
    order_request: OrderRequest
    passed: bool
    failures: list[str]


class OrderEvent(_BaseEvent):
    """An order was submitted to the exchange."""

    event_type: str = "execution.order"
    order: OrderState


class FillEvent(_BaseEvent):
    """A (partial or full) fill was received for an order."""

    event_type: str = "execution.fill"
    exchange_order_id: str
    client_order_id: str
    symbol: str
    exchange: ExchangeId
    filled_quantity: str
    fill_price: str
    is_partial: bool
    commission: str = "0"
    commission_asset: str = ""


class ExecutionEvent(_BaseEvent):
    """Final execution state — order fully resolved (filled/cancelled/rejected)."""

    event_type: str = "execution.resolved"
    order: OrderState


class ReconciliationEvent(_BaseEvent):
    """Periodic reconciliation between OMS state and exchange state."""

    event_type: str = "execution.reconciliation"
    exchange: ExchangeId
    oms_position_count: int
    exchange_position_count: int
    matched: bool
    discrepancies: list[str]


# ---------------------------------------------------------------------------
# Portfolio Events
# ---------------------------------------------------------------------------


class PortfolioEvent(_BaseEvent):
    """Portfolio state changed."""

    event_type: str = "portfolio.update"
    snapshot: PortfolioSnapshot


# ---------------------------------------------------------------------------
# System / Health Events
# ---------------------------------------------------------------------------


class SystemEvent(_BaseEvent):
    """System lifecycle event (startup, shutdown, restart)."""

    event_type: str = "system.lifecycle"
    action: str  # "startup" | "shutdown" | "restart"
    component: str
    message: str = ""


class HealthEvent(_BaseEvent):
    """Component health state changed."""

    event_type: str = "system.health"
    component: str
    healthy: bool
    message: str = ""


class AlertEvent(_BaseEvent):
    """An alert was triggered (kill switch, drawdown, anomaly)."""

    event_type: str = "system.alert"
    severity: str  # "info" | "warning" | "critical" | "emergency"
    title: str
    message: str
    runbook_url: str = ""
    acknowledged: bool = False


class FlagChangeEvent(_BaseEvent):
    """A feature flag was toggled."""

    event_type: str = "system.flag_change"
    flag_name: str
    old_value: bool | None
    new_value: bool
    changed_by: str
    reason: str = ""


# ---------------------------------------------------------------------------
# Event type registry — for deserialization during replay
# ---------------------------------------------------------------------------

EVENT_REGISTRY: dict[str, type[_BaseEvent]] = {
    "market.ohlcv": MarketEvent,
    "market.ticker": TickerEvent,
    "market.staleness": DataStalenessEvent,
    "strategy.signal": SignalEvent,
    "risk.evaluation": RiskEvent,
    "risk.drawdown_breach": DrawdownBreachEvent,
    "execution.pre_trade_check": PreTradeCheckEvent,
    "execution.order": OrderEvent,
    "execution.fill": FillEvent,
    "execution.resolved": ExecutionEvent,
    "execution.reconciliation": ReconciliationEvent,
    "portfolio.update": PortfolioEvent,
    "system.lifecycle": SystemEvent,
    "system.health": HealthEvent,
    "system.alert": AlertEvent,
    "system.flag_change": FlagChangeEvent,
}
