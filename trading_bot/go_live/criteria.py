"""Go-live readiness criteria — Pydantic models and evaluation results.

Each GoLiveCriterion maps to one required condition that must be satisfied
before live trading is permitted. The ReadinessReport aggregates all results
and provides a single ready: bool answer.

Criteria are evaluated by GoLiveGate (gate.py). They can also be
manually overridden with an operator signature in the approval store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class CriterionStatus(StrEnum):
    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    WARNING = "warning"  # non-blocking advisory
    SKIPPED = "skipped"  # not applicable in this environment


# ---------------------------------------------------------------------------
# Per-criterion result
# ---------------------------------------------------------------------------


class CriterionResult(BaseModel):
    """Outcome of evaluating a single go-live criterion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_id: str
    label: str
    status: CriterionStatus
    detail: str = ""
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    blocking: bool = True  # FAIL on a blocking criterion = overall FAIL


# ---------------------------------------------------------------------------
# Approval event (persisted to DB)
# ---------------------------------------------------------------------------


class ApprovalEvent(BaseModel):
    """Records that an operator manually approved the go-live checklist."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    approval_id: str = Field(default_factory=lambda: __import__("uuid").uuid4().__str__())
    operator: str
    approved: bool
    comment: str = ""
    approved_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    checklist_snapshot: dict[str, Any] = Field(default_factory=dict)
    rollback_plan_confirmed: bool = False
    risk_sign_off_by: str = ""


# ---------------------------------------------------------------------------
# ReadinessChecklist definition
# ---------------------------------------------------------------------------


class GoLiveCriterion(BaseModel):
    """Definition of a single go-live requirement (not the result)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion_id: str
    label: str
    description: str
    blocking: bool = True


STANDARD_CRITERIA: list[GoLiveCriterion] = [
    GoLiveCriterion(
        criterion_id="dry_run_completed",
        label="Dry-run completed",
        description=(
            "At least one full paper-trading session with ≥7 days of signals must be recorded."
        ),
    ),
    GoLiveCriterion(
        criterion_id="paper_live_parity",
        label="Paper/live parity report",
        description=(
            "Paper trading metrics must be within acceptable bounds vs backtest baseline: "
            "win-rate ≥80% of backtest, drawdown ≤120% of backtest."
        ),
    ),
    GoLiveCriterion(
        criterion_id="risk_sign_off",
        label="Risk sign-off",
        description="A named operator must explicitly sign off on risk parameters before go-live.",
    ),
    GoLiveCriterion(
        criterion_id="rollback_plan_present",
        label="Rollback plan present",
        description=(
            "A documented rollback plan (runbook entry) must exist. "
            "It must describe how to disable live trading, flatten positions, and restore state."
        ),
    ),
    GoLiveCriterion(
        criterion_id="operator_approval",
        label="Operator approval",
        description="An operator approval event must be recorded in the audit log.",
    ),
    GoLiveCriterion(
        criterion_id="exchange_permissions",
        label="Exchange permissions audit",
        description=(
            "Exchange API key must have: read + trade permissions. "
            "Withdraw permission must be ABSENT."
        ),
    ),
    GoLiveCriterion(
        criterion_id="feature_flags_confirmed",
        label="Feature flag confirmation",
        description=(
            "paper_trading_enabled=true, websocket_enabled=true, "
            "live_trading_enabled=false (gate will flip this last)."
        ),
    ),
    GoLiveCriterion(
        criterion_id="circuit_breakers_configured",
        label="Circuit breakers configured",
        description=(
            "All three drawdown tiers must be configured with non-default (tightened) values."
        ),
        blocking=False,  # advisory — can proceed with defaults but warned
    ),
    GoLiveCriterion(
        criterion_id="capital_policy_configured",
        label="Capital allocation policy configured",
        description="Per-strategy and per-asset capital limits must be explicitly set.",
        blocking=False,
    ),
    GoLiveCriterion(
        criterion_id="reconciler_healthy",
        label="Reconciler last run clean",
        description=(
            "OMS reconciler must have completed at least one clean run with zero discrepancies."
        ),
    ),
]

CRITERIA_BY_ID: dict[str, GoLiveCriterion] = {c.criterion_id: c for c in STANDARD_CRITERIA}


# ---------------------------------------------------------------------------
# ReadinessReport
# ---------------------------------------------------------------------------


class ReadinessReport(BaseModel):
    """Aggregated go-live readiness assessment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    results: list[CriterionResult]
    operator_approval: ApprovalEvent | None = None

    @property
    def ready(self) -> bool:
        """True only if ALL blocking criteria passed and operator approved."""
        blocking_failures = [
            r for r in self.results if r.blocking and r.status == CriterionStatus.FAIL
        ]
        return (
            len(blocking_failures) == 0
            and self.operator_approval is not None
            and self.operator_approval.approved
        )

    @property
    def failed_blocking(self) -> list[CriterionResult]:
        return [r for r in self.results if r.blocking and r.status == CriterionStatus.FAIL]

    @property
    def warnings(self) -> list[CriterionResult]:
        return [r for r in self.results if r.status == CriterionStatus.WARNING]

    def summary(self) -> str:
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == CriterionStatus.PASS)
        failed = len(self.failed_blocking)
        warn = len(self.warnings)
        approved = "YES" if (self.operator_approval and self.operator_approval.approved) else "NO"
        status = "READY" if self.ready else "NOT READY"
        return (
            f"Go-Live Readiness: {status} | "
            f"{passed}/{total} passed | {failed} blocking failures | "
            f"{warn} warnings | operator_approved={approved}"
        )
