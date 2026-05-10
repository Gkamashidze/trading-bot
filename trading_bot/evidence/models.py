"""Pydantic v2 models for the Paper Testing Evidence Store.

All models use UTC-aware datetimes only. Naive datetimes are rejected at
validation time by the utc_datetime validator.

Idempotency keys are application-generated (e.g. SHA256 of content hash)
and stored as TEXT UNIQUE in Postgres — duplicates are silently dropped via
ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _require_utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("datetime must be UTC-aware; naive datetimes are rejected")
    return v


class SessionStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class EvidenceSource(StrEnum):
    SCHEDULER = "scheduler"
    DASHBOARD = "dashboard"
    MANUAL = "manual"
    STARTUP = "startup"


class ReconciliationSeverity(StrEnum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class MicroLiveRecommendation(StrEnum):
    CONTINUE_PAPER = "continue_paper"
    FIX_ISSUES = "fix_issues"
    ELIGIBLE_FOR_REVIEW = "eligible_for_micro_live_review"
    REJECT_STRATEGY = "reject_strategy"


# ---------------------------------------------------------------------------
# A. PaperSession
# ---------------------------------------------------------------------------


class PaperSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    session_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    started_at: datetime
    ended_at: datetime | None = None
    environment: str
    git_commit: str | None = None
    config_snapshot_hash: str
    paper_capital: Decimal
    symbols: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    status: SessionStatus = SessionStatus.RUNNING
    notes: str = ""

    _val_started_at = field_validator("started_at", mode="after")(_require_utc)
    _val_ended_at = field_validator("ended_at", mode="after")(
        lambda cls, v: _require_utc(v) if v is not None else v
    )


# ---------------------------------------------------------------------------
# B. PortfolioEvidenceSnapshot
# ---------------------------------------------------------------------------


class PortfolioEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    captured_at: datetime
    cash_balance: Decimal
    total_equity: Decimal
    daily_pnl: Decimal
    daily_drawdown_pct: Decimal
    positions: dict[str, Any] = Field(default_factory=dict)
    source: EvidenceSource = EvidenceSource.SCHEDULER
    idempotency_key: str

    _val_captured_at = field_validator("captured_at", mode="after")(_require_utc)


# ---------------------------------------------------------------------------
# C. SignalEvidenceSnapshot
# ---------------------------------------------------------------------------


class SignalEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    captured_at: datetime
    symbol: str
    strategy_id: str
    signal: str
    strength: Decimal | None = None
    indicators: dict[str, Any] = Field(default_factory=dict)
    bars_used: int | None = None
    market_context: dict[str, Any] | None = None
    idempotency_key: str

    _val_captured_at = field_validator("captured_at", mode="after")(_require_utc)


# ---------------------------------------------------------------------------
# D. BacktestEvidenceSnapshot
# ---------------------------------------------------------------------------


class BacktestEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    captured_at: datetime
    strategy_id: str
    symbol: str
    dataset_snapshot_ids: list[str] = Field(default_factory=list)
    period_start: datetime
    period_end: datetime
    metrics: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    gross_return_pct: Decimal | None = None
    net_return_pct: Decimal | None = None
    max_drawdown_pct: Decimal | None = None
    sharpe: Decimal | None = None
    total_trades: int | None = None
    idempotency_key: str

    _val_captured_at = field_validator("captured_at", mode="after")(_require_utc)
    _val_period_start = field_validator("period_start", mode="after")(_require_utc)
    _val_period_end = field_validator("period_end", mode="after")(_require_utc)


# ---------------------------------------------------------------------------
# E. TCAEvidenceRecord
# ---------------------------------------------------------------------------


class TCAEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    captured_at: datetime
    order_id: str
    symbol: str
    strategy_id: str = ""
    side: str
    signal_price: Decimal
    fill_price: Decimal
    quantity: Decimal
    fee_paid: Decimal = Decimal("0")
    slippage_pct: Decimal = Decimal("0")
    slippage_usdt: Decimal = Decimal("0")
    latency_ms: Decimal = Decimal("0")
    quality_score: str = "excellent"
    outcome: str
    retry_count: int = 0
    idempotency_key: str

    _val_captured_at = field_validator("captured_at", mode="after")(_require_utc)


# ---------------------------------------------------------------------------
# F. AccountingEvidenceRecord
# ---------------------------------------------------------------------------


class AccountingEvidenceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    record_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    captured_at: datetime
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    fee_usdt: Decimal = Decimal("0")
    realized_pnl: Decimal | None = None
    cost_basis: Decimal | None = None
    lot_id: str | None = None
    idempotency_key: str

    _val_captured_at = field_validator("captured_at", mode="after")(_require_utc)


# ---------------------------------------------------------------------------
# G. ReconciliationEvidenceReport
# ---------------------------------------------------------------------------


class ReconciliationEvidenceReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    report_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    run_at: datetime
    severity: ReconciliationSeverity
    order_discrepancies: list[str] = Field(default_factory=list)
    balance_discrepancies: list[str] = Field(default_factory=list)
    position_discrepancies: list[str] = Field(default_factory=list)
    orders_blocked: bool = False
    mismatch_count: int = 0
    idempotency_key: str

    _val_run_at = field_validator("run_at", mode="after")(_require_utc)


# ---------------------------------------------------------------------------
# H. AlertIncidentEvidence
# ---------------------------------------------------------------------------


class AlertIncidentEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    incident_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    fired_at: datetime
    cleared_at: datetime | None = None
    severity: AlertSeverity
    source: str = ""
    title: str
    detail: str = ""
    acknowledged: bool = False
    acknowledged_by: str | None = None
    runbook_url: str | None = None
    idempotency_key: str

    _val_fired_at = field_validator("fired_at", mode="after")(_require_utc)
    _val_cleared_at = field_validator("cleared_at", mode="after")(
        lambda cls, v: _require_utc(v) if v is not None else v
    )


# ---------------------------------------------------------------------------
# I. DailyEvidenceSummary
# ---------------------------------------------------------------------------


class DailyEvidenceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    summary_date: date
    starting_equity: Decimal
    ending_equity: Decimal
    pnl: Decimal
    pnl_pct: Decimal
    max_drawdown_pct: Decimal = Decimal("0")
    trade_count: int = 0
    rejected_order_count: int = 0
    partial_fill_count: int = 0
    signal_count: int = 0
    reconciliation_critical_count: int = 0
    alert_count: int = 0
    incident_count: int = 0
    notes: str = ""
    generated_at: datetime
    idempotency_key: str

    _val_generated_at = field_validator("generated_at", mode="after")(_require_utc)


# ---------------------------------------------------------------------------
# J. WeeklyEvidenceSummary
# ---------------------------------------------------------------------------


class WeeklyEvidenceSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    summary_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    week_start: date
    week_end: date
    starting_equity: Decimal
    ending_equity: Decimal
    pnl: Decimal
    pnl_pct: Decimal
    max_drawdown_pct: Decimal = Decimal("0")
    trade_count: int = 0
    rejected_order_count: int = 0
    partial_fill_count: int = 0
    parity_score: Decimal | None = None
    strategy_metrics: dict[str, Any] = Field(default_factory=dict)
    incidents: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: datetime
    idempotency_key: str

    _val_generated_at = field_validator("generated_at", mode="after")(_require_utc)


# ---------------------------------------------------------------------------
# Report output models (not persisted, constructed from DB reads)
# ---------------------------------------------------------------------------


class MicroLiveReadinessCheck(BaseModel):
    """Single acceptance criterion result."""

    model_config = ConfigDict(frozen=True)

    criterion: str
    passed: bool
    actual_value: str
    threshold: str
    detail: str = ""


class FinalPaperTestReport(BaseModel):
    """Output of the 30-day final paper testing report generator."""

    model_config = ConfigDict(frozen=True)

    session_id: uuid.UUID
    generated_at: datetime
    days_observed: int
    trade_count: int
    rejected_order_count: int
    partial_fill_count: int
    max_drawdown_pct: Decimal
    total_pnl: Decimal
    gross_return_pct: Decimal | None
    net_return_pct: Decimal | None
    avg_slippage_pct: Decimal
    avg_latency_ms: Decimal
    reconciliation_critical_count: int
    alert_count: int
    incident_count: int
    parity_score: Decimal | None
    readiness_checks: list[MicroLiveReadinessCheck]
    recommendation: MicroLiveRecommendation
    recommendation_rationale: str

    _val_generated_at = field_validator("generated_at", mode="after")(_require_utc)
