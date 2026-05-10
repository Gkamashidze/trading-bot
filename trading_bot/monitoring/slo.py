"""SLI/SLO definitions and alert management.

Defines Service Level Indicators (SLIs), their SLO targets, alert severity
levels, and a lightweight in-memory alert registry.

SLIs tracked:
  WEBSOCKET_FRESHNESS       — seconds since last tick < threshold
  ORDER_LATENCY             — p95 order-submit-to-fill latency
  REJECTED_ORDER_RATE       — rejected_orders / total_orders over window
  RECONCILIATION_LAG        — time since last successful reconciliation
  DATA_INGESTION_FRESHNESS  — time since last successful OHLCV ingest

Alert lifecycle:
  fired → (optionally) acknowledged → auto-cleared on next healthy check

All alert records are stored in memory.  A future migration can persist
them to Postgres using the audit_log table.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from prometheus_client import Counter, Gauge

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------

_SLI_GAUGE = Gauge(
    "trading_sli_value",
    "Current SLI measurement",
    labelnames=["sli"],
)

_ALERT_FIRED = Counter(
    "trading_slo_alerts_fired_total",
    "Number of SLO alerts fired",
    labelnames=["sli", "severity"],
)

_ALERT_ACKED = Counter(
    "trading_slo_alerts_acknowledged_total",
    "Number of SLO alerts acknowledged by an operator",
    labelnames=["sli"],
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SLIName(StrEnum):
    WEBSOCKET_FRESHNESS = "websocket_freshness"
    ORDER_LATENCY = "order_latency"
    REJECTED_ORDER_RATE = "rejected_order_rate"
    RECONCILIATION_LAG = "reconciliation_lag"
    DATA_INGESTION_FRESHNESS = "data_ingestion_freshness"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    PAGE = "page"


# ---------------------------------------------------------------------------
# SLO target definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SLOTarget:
    """Threshold configuration for a single SLI."""

    sli: SLIName
    warning_threshold: float  # breaching this fires WARNING
    critical_threshold: float  # breaching this fires CRITICAL
    unit: str  # "seconds" | "ms" | "fraction" — for display
    runbook_url: str = ""
    description: str = ""

    def severity_for(self, value: float) -> AlertSeverity | None:
        """Return the appropriate severity if the value breaches a threshold."""
        if value >= self.critical_threshold:
            return AlertSeverity.CRITICAL
        if value >= self.warning_threshold:
            return AlertSeverity.WARNING
        return None


DEFAULT_SLO_TARGETS: dict[SLIName, SLOTarget] = {
    SLIName.WEBSOCKET_FRESHNESS: SLOTarget(
        sli=SLIName.WEBSOCKET_FRESHNESS,
        warning_threshold=30.0,  # 30 s without a tick → WARNING
        critical_threshold=120.0,  # 2 min → CRITICAL
        unit="seconds",
        description="Seconds since last WebSocket price tick",
        runbook_url="docs/runbooks/websocket-staleness.md",
    ),
    SLIName.ORDER_LATENCY: SLOTarget(
        sli=SLIName.ORDER_LATENCY,
        warning_threshold=500.0,  # 500 ms p95 → WARNING
        critical_threshold=2000.0,  # 2 s p95 → CRITICAL
        unit="ms",
        description="p95 order-submit-to-fill latency",
        runbook_url="docs/runbooks/order-latency.md",
    ),
    SLIName.REJECTED_ORDER_RATE: SLOTarget(
        sli=SLIName.REJECTED_ORDER_RATE,
        warning_threshold=0.05,  # >5% rejected → WARNING
        critical_threshold=0.20,  # >20% rejected → CRITICAL
        unit="fraction",
        description="Fraction of orders rejected over the last 5 minutes",
        runbook_url="docs/runbooks/order-rejection-rate.md",
    ),
    SLIName.RECONCILIATION_LAG: SLOTarget(
        sli=SLIName.RECONCILIATION_LAG,
        warning_threshold=300.0,  # 5 min without reconciliation → WARNING
        critical_threshold=900.0,  # 15 min → CRITICAL
        unit="seconds",
        description="Seconds since last successful OMS reconciliation",
        runbook_url="docs/runbooks/reconciliation-lag.md",
    ),
    SLIName.DATA_INGESTION_FRESHNESS: SLOTarget(
        sli=SLIName.DATA_INGESTION_FRESHNESS,
        warning_threshold=3600.0,  # 1 h stale → WARNING
        critical_threshold=86400.0,  # 24 h → CRITICAL
        unit="seconds",
        description="Seconds since last successful OHLCV ingest",
        runbook_url="docs/runbooks/data-ingestion-freshness.md",
    ),
}


# ---------------------------------------------------------------------------
# Alert records
# ---------------------------------------------------------------------------


@dataclass
class AlertRecord:
    """A single fired alert instance."""

    alert_id: str
    sli: SLIName
    severity: AlertSeverity
    value: float
    threshold: float
    fired_at: datetime
    runbook_url: str = ""
    acknowledged: bool = False
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    cleared_at: datetime | None = None
    notes: str = ""

    @property
    def is_active(self) -> bool:
        return self.cleared_at is None


# ---------------------------------------------------------------------------
# Routing policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AlertRoutingPolicy:
    """Maps severity levels to notification channels."""

    info_channels: list[str] = field(default_factory=lambda: ["log"])
    warning_channels: list[str] = field(default_factory=lambda: ["log", "telegram"])
    critical_channels: list[str] = field(default_factory=lambda: ["log", "telegram"])
    page_channels: list[str] = field(default_factory=lambda: ["log", "telegram", "pagerduty"])

    def channels_for(self, severity: AlertSeverity) -> list[str]:
        mapping = {
            AlertSeverity.INFO: self.info_channels,
            AlertSeverity.WARNING: self.warning_channels,
            AlertSeverity.CRITICAL: self.critical_channels,
            AlertSeverity.PAGE: self.page_channels,
        }
        return mapping[severity]


DEFAULT_ROUTING_POLICY = AlertRoutingPolicy()


# ---------------------------------------------------------------------------
# SLO Monitor
# ---------------------------------------------------------------------------


class SLOMonitor:
    """Evaluates SLI measurements against SLO targets and manages alerts."""

    def __init__(
        self,
        targets: dict[SLIName, SLOTarget] | None = None,
        routing: AlertRoutingPolicy | None = None,
    ) -> None:
        self._targets = targets if targets is not None else DEFAULT_SLO_TARGETS
        self._routing = routing or DEFAULT_ROUTING_POLICY
        self._active_alerts: dict[str, AlertRecord] = {}
        self._alert_history: list[AlertRecord] = []

    # ------------------------------------------------------------------

    def record(self, sli: SLIName, value: float) -> AlertRecord | None:
        """Record a new SLI measurement. Returns a new AlertRecord if an SLO
        is breached, None if everything is within target."""
        _SLI_GAUGE.labels(sli=sli).set(value)

        target = self._targets.get(sli)
        if target is None:
            return None

        severity = target.severity_for(value)
        if severity is None:
            self._auto_clear(sli)
            return None

        return self._fire_alert(sli, severity, value, target)

    def acknowledge(
        self,
        alert_id: str,
        operator: str,
        notes: str = "",
    ) -> AlertRecord:
        """Acknowledge an active alert. Raises KeyError if not found."""
        alert = self._active_alerts[alert_id]
        alert.acknowledged = True
        alert.acknowledged_at = datetime.now(UTC)
        alert.acknowledged_by = operator
        alert.notes = notes
        _ALERT_ACKED.labels(sli=alert.sli).inc()
        log.info(
            "slo_alert_acknowledged",
            alert_id=alert_id,
            sli=alert.sli,
            operator=operator,
        )
        return alert

    def active_alerts(self, sli: SLIName | None = None) -> list[AlertRecord]:
        alerts = [a for a in self._active_alerts.values() if a.is_active]
        if sli is not None:
            alerts = [a for a in alerts if a.sli == sli]
        return sorted(alerts, key=lambda a: a.fired_at)

    def alert_history(self) -> list[AlertRecord]:
        return list(self._alert_history)

    # ------------------------------------------------------------------

    def _fire_alert(
        self,
        sli: SLIName,
        severity: AlertSeverity,
        value: float,
        target: SLOTarget,
    ) -> AlertRecord:
        threshold = (
            target.critical_threshold
            if severity in (AlertSeverity.CRITICAL, AlertSeverity.PAGE)
            else target.warning_threshold
        )
        alert = AlertRecord(
            alert_id=str(uuid.uuid4()),
            sli=sli,
            severity=severity,
            value=value,
            threshold=threshold,
            fired_at=datetime.now(UTC),
            runbook_url=target.runbook_url,
        )
        self._active_alerts[alert.alert_id] = alert
        self._alert_history.append(alert)
        _ALERT_FIRED.labels(sli=sli, severity=severity).inc()

        channels = self._routing.channels_for(severity)
        log.warning(
            "slo_alert_fired",
            sli=sli,
            severity=severity,
            value=round(value, 4),
            threshold=threshold,
            alert_id=alert.alert_id,
            channels=channels,
            runbook=target.runbook_url,
        )
        return alert

    def _auto_clear(self, sli: SLIName) -> None:
        """Clear any active (non-acknowledged) alerts for an SLI that is now healthy."""
        cleared = []
        for alert_id, alert in list(self._active_alerts.items()):
            if alert.sli == sli and not alert.acknowledged:
                alert.cleared_at = datetime.now(UTC)
                cleared.append(alert_id)
        for alert_id in cleared:
            del self._active_alerts[alert_id]
        if cleared:
            log.info("slo_alerts_auto_cleared", sli=sli, count=len(cleared))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_monitor: SLOMonitor = SLOMonitor()


def get_slo_monitor() -> SLOMonitor:
    return _monitor
