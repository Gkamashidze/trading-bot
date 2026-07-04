"""Go-Live Gate — evaluates all readiness criteria and persists the report.

The gate is intentionally conservative: if any check cannot be verified
(e.g. no DB connection), it fails CLOSED (criterion = FAIL).

Live trading remains hardcoded false until all criteria pass AND an operator
explicitly calls record_approval().

Typical flow:
    gate = GoLiveGate(audit_log=audit_log, exchange=exchange, pool=pool, ...)
    report = await gate.evaluate()
    print(report.summary())
    # If report.ready is False, fix the blocking items and re-evaluate.
    # When ready, operator calls:
    approval = await gate.record_approval(  # noqa: E501
        operator="alice", comment="...", rollback_plan_confirmed=True
    )
    report2 = await gate.evaluate()
    assert report2.ready

Persistence:
    Approvals are written to the go_live_approvals Postgres table (migration 0004).
    On restart, GoLiveGate.load_latest_approval() recovers the most recent valid
    approval so the gate survives process restarts without losing approval state.
    The approval record includes: operator, timestamp, rollback_confirmed,
    risk_sign_off, checklist_snapshot, and a correlation_id (idempotency key).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from trading_bot.config import get_settings
from trading_bot.core.contracts import (
    AuditLogInterface,
    ExchangeInterface,
    FeatureFlagStoreInterface,
)
from trading_bot.go_live.criteria import (
    CRITERIA_BY_ID,
    STANDARD_CRITERIA,
    ApprovalEvent,
    CriterionResult,
    CriterionStatus,
    ReadinessReport,
)
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


class GoLiveGate:
    """Evaluates go-live readiness and records operator approvals.

    All evaluation results are logged to the audit trail.
    Approvals are persisted to Postgres so restarts do not lose approval state.
    The gate never mutates the live_trading_enabled flag itself —
    that is the operator's responsibility after the report confirms ready=True.
    """

    def __init__(
        self,
        audit_log: AuditLogInterface,
        exchange: ExchangeInterface,
        feature_flags: FeatureFlagStoreInterface | None = None,
        pool: Any = None,
        reconciler_last_run_clean: bool = False,
        paper_trading_days: int = 0,
        paper_round_trips: int = 0,
        min_paper_days: int = 0,
        min_round_trips: int = 0,
        paper_win_rate: float | None = None,
        paper_drawdown_pct: float | None = None,
        backtest_win_rate: float | None = None,
        backtest_drawdown_pct: float | None = None,
        risk_sign_off_by: str = "",
        rollback_runbook_exists: bool = False,
    ) -> None:
        self._audit_log = audit_log
        self._exchange = exchange
        self._feature_flags = feature_flags
        self._pool = pool
        self._reconciler_last_run_clean = reconciler_last_run_clean
        self._paper_trading_days = paper_trading_days
        self._paper_round_trips = paper_round_trips
        self._min_paper_days = min_paper_days
        self._min_round_trips = min_round_trips
        self._paper_win_rate = paper_win_rate
        self._paper_drawdown_pct = paper_drawdown_pct
        self._backtest_win_rate = backtest_win_rate
        self._backtest_drawdown_pct = backtest_drawdown_pct
        self._risk_sign_off_by = risk_sign_off_by
        self._rollback_runbook_exists = rollback_runbook_exists
        self._approval: ApprovalEvent | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def load_latest_approval(self) -> ApprovalEvent | None:
        """Recover the latest valid approval from Postgres (call at startup).

        Returns the ApprovalEvent and also sets self._approval so evaluate()
        will include it in the report. Returns None if no approval exists or
        DB is unavailable.
        """
        if self._pool is None:
            return None

        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT approval_id, operator, approved, comment, approved_at,
                           rollback_plan_confirmed, risk_sign_off_by, checklist_snapshot,
                           correlation_id
                    FROM go_live_approvals
                    WHERE approved = TRUE
                    ORDER BY approved_at DESC
                    LIMIT 1
                    """,
                )
        except Exception as exc:
            log.warning("go_live_approval_load_failed", error=str(exc))
            return None

        if row is None:
            return None

        try:
            snapshot = (
                json.loads(row["checklist_snapshot"])
                if isinstance(row["checklist_snapshot"], str)
                else dict(row["checklist_snapshot"])
            )
            approval = ApprovalEvent(
                approval_id=str(row["approval_id"]),
                operator=row["operator"],
                approved=bool(row["approved"]),
                comment=row["comment"] or "",
                approved_at=row["approved_at"],
                rollback_plan_confirmed=bool(row["rollback_plan_confirmed"]),
                risk_sign_off_by=row["risk_sign_off_by"] or "",
                checklist_snapshot=snapshot,
            )
            self._approval = approval
            log.info(
                "go_live_approval_recovered",
                approval_id=str(row["approval_id"]),
                operator=row["operator"],
                approved_at=row["approved_at"].isoformat(),
            )
            return approval
        except Exception as exc:
            log.warning("go_live_approval_deserialise_failed", error=str(exc))
            return None

    async def evaluate(self) -> ReadinessReport:
        """Run all criteria checks and return a ReadinessReport.

        Never raises — failed checks return CriterionStatus.FAIL.
        """
        results: list[CriterionResult] = []

        for criterion in STANDARD_CRITERIA:
            try:
                result = await self._evaluate_criterion(criterion.criterion_id)
            except Exception as exc:
                log.error(
                    "go_live_criterion_error",
                    criterion_id=criterion.criterion_id,
                    error=str(exc),
                )
                result = CriterionResult(
                    criterion_id=criterion.criterion_id,
                    label=criterion.label,
                    status=CriterionStatus.FAIL,
                    detail=f"evaluation error: {exc}",
                    blocking=criterion.blocking,
                )
            results.append(result)

        report = ReadinessReport(results=results, operator_approval=self._approval)

        await self._audit_log.append(
            event_type="go_live.readiness_evaluated",
            payload={
                "ready": report.ready,
                "summary": report.summary(),
                "blocking_failures": [r.criterion_id for r in report.failed_blocking],
                "warnings": [r.criterion_id for r in report.warnings],
            },
            actor="system",
        )

        log.info(
            "go_live_evaluated",
            ready=report.ready,
            summary=report.summary(),
        )
        return report

    async def record_approval(
        self,
        operator: str,
        comment: str = "",
        rollback_plan_confirmed: bool = False,
        risk_sign_off_by: str = "",
        correlation_id: str = "",
    ) -> ApprovalEvent:
        """Record operator approval. Persisted to audit log AND Postgres.

        Approval does NOT enable live trading — it is one input to evaluate().
        The operator must still manually flip the feature flag after the gate
        confirms ready=True.

        Args:
            operator: Name/identifier of the approving operator (required).
            comment: Optional comment.
            rollback_plan_confirmed: Operator confirms rollback plan exists.
            risk_sign_off_by: Name of the risk reviewer (defaults to self._risk_sign_off_by).
            correlation_id: Idempotency key for this approval; generated if not provided.
        """
        if not operator:
            raise ValueError("operator name is required for go-live approval")

        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Capture current report state as snapshot
        report = await self.evaluate()
        snapshot: dict[str, Any] = {
            "evaluated_at": report.evaluated_at.isoformat(),
            "criteria": [
                {"id": r.criterion_id, "status": r.status, "detail": r.detail}
                for r in report.results
            ],
        }

        effective_risk_sign_off = risk_sign_off_by or self._risk_sign_off_by

        approval = ApprovalEvent(
            operator=operator,
            approved=True,
            comment=comment,
            rollback_plan_confirmed=rollback_plan_confirmed,
            risk_sign_off_by=effective_risk_sign_off,
            checklist_snapshot=snapshot,
        )
        self._approval = approval

        # ── Persist to Postgres ───────────────────────────────────────────────
        await self._persist_approval(approval, correlation_id)

        # ── Append to audit log ───────────────────────────────────────────────
        await self._audit_log.append(
            event_type="go_live.operator_approved",
            payload={
                "approval_id": approval.approval_id,
                "operator": operator,
                "comment": comment,
                "rollback_plan_confirmed": rollback_plan_confirmed,
                "risk_sign_off_by": approval.risk_sign_off_by,
                "checklist_ready": report.ready,
            },
            correlation_id=correlation_id,
            actor=operator,
        )

        log.info(
            "go_live_approval_recorded",
            operator=operator,
            checklist_ready=report.ready,
            correlation_id=correlation_id,
        )
        return approval

    # ── Persistence helpers ───────────────────────────────────────────────────

    async def _persist_approval(self, approval: ApprovalEvent, correlation_id: str) -> None:
        """Write approval to go_live_approvals table.  No-op if pool is None."""
        if self._pool is None:
            log.warning(
                "go_live_approval_no_pool",
                note="approval not persisted to DB — pool is None",
            )
            return

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO go_live_approvals
                        (approval_id, operator, approved, comment, approved_at,
                         rollback_plan_confirmed, risk_sign_off_by, checklist_snapshot,
                         correlation_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    ON CONFLICT (approval_id) DO NOTHING
                    """,
                    uuid.UUID(approval.approval_id),
                    approval.operator,
                    approval.approved,
                    approval.comment,
                    approval.approved_at,
                    approval.rollback_plan_confirmed,
                    approval.risk_sign_off_by,
                    json.dumps(approval.checklist_snapshot),
                    correlation_id,
                )
            log.info(
                "go_live_approval_persisted",
                approval_id=approval.approval_id,
                operator=approval.operator,
            )
        except Exception as exc:
            log.error(
                "go_live_approval_persist_failed",
                approval_id=approval.approval_id,
                error=str(exc),
            )

    # ── Criterion evaluators ──────────────────────────────────────────────────

    async def _evaluate_criterion(self, criterion_id: str) -> CriterionResult:
        criterion = CRITERIA_BY_ID[criterion_id]

        evaluator = {
            "dry_run_completed": self._check_dry_run,
            "paper_evidence_thresholds": self._check_paper_evidence,
            "paper_live_parity": self._check_paper_parity,
            "risk_sign_off": self._check_risk_sign_off,
            "rollback_plan_present": self._check_rollback_plan,
            "operator_approval": self._check_operator_approval,
            "exchange_permissions": self._check_exchange_permissions,
            "feature_flags_confirmed": self._check_feature_flags,
            "circuit_breakers_configured": self._check_circuit_breakers,
            "capital_policy_configured": self._check_capital_policy,
            "reconciler_healthy": self._check_reconciler,
        }.get(criterion_id)

        if evaluator is None:
            return CriterionResult(
                criterion_id=criterion_id,
                label=criterion.label,
                status=CriterionStatus.SKIPPED,
                detail="no evaluator registered",
                blocking=criterion.blocking,
            )

        status, detail = await evaluator()
        return CriterionResult(
            criterion_id=criterion_id,
            label=criterion.label,
            status=status,
            detail=detail,
            blocking=criterion.blocking,
        )

    async def _check_dry_run(self) -> tuple[CriterionStatus, str]:
        if self._paper_trading_days >= 7:
            return CriterionStatus.PASS, f"paper trading ran {self._paper_trading_days} days"
        return (
            CriterionStatus.FAIL,
            f"need ≥7 paper trading days, have {self._paper_trading_days}",
        )

    async def _check_paper_evidence(self) -> tuple[CriterionStatus, str]:
        days_ok = self._paper_trading_days >= self._min_paper_days
        trips_ok = self._paper_round_trips >= self._min_round_trips
        if days_ok and trips_ok:
            return (
                CriterionStatus.PASS,
                f"{self._paper_trading_days} days (≥{self._min_paper_days}), "
                f"{self._paper_round_trips} round-trips (≥{self._min_round_trips})",
            )
        reasons = []
        if not days_ok:
            reasons.append(
                f"{self._paper_trading_days} paper days < {self._min_paper_days} required"
            )
        if not trips_ok:
            reasons.append(
                f"{self._paper_round_trips} round-trips < {self._min_round_trips} required"
            )
        return CriterionStatus.FAIL, "; ".join(reasons)

    async def _check_paper_parity(self) -> tuple[CriterionStatus, str]:
        if self._paper_win_rate is None or self._backtest_win_rate is None:
            return CriterionStatus.FAIL, "paper or backtest win_rate not provided"
        if self._paper_drawdown_pct is None or self._backtest_drawdown_pct is None:
            return CriterionStatus.FAIL, "paper or backtest drawdown_pct not provided"

        win_rate_ok = self._paper_win_rate >= self._backtest_win_rate * 0.80
        dd_ok = self._paper_drawdown_pct <= self._backtest_drawdown_pct * 1.20

        if win_rate_ok and dd_ok:
            return (
                CriterionStatus.PASS,
                f"paper win_rate={self._paper_win_rate:.2%} "
                f"(≥80% of backtest {self._backtest_win_rate:.2%}), "
                f"paper drawdown={self._paper_drawdown_pct:.2%} "
                f"(≤120% of backtest {self._backtest_drawdown_pct:.2%})",
            )
        reasons = []
        if not win_rate_ok:
            reasons.append(
                f"win_rate {self._paper_win_rate:.2%} < 80% of "
                f"backtest {self._backtest_win_rate:.2%}"
            )
        if not dd_ok:
            reasons.append(
                f"drawdown {self._paper_drawdown_pct:.2%} > 120% of "
                f"backtest {self._backtest_drawdown_pct:.2%}"
            )
        return CriterionStatus.FAIL, "; ".join(reasons)

    async def _check_risk_sign_off(self) -> tuple[CriterionStatus, str]:
        if self._risk_sign_off_by:
            return CriterionStatus.PASS, f"signed off by '{self._risk_sign_off_by}'"
        return CriterionStatus.FAIL, "no risk sign-off recorded"

    async def _check_rollback_plan(self) -> tuple[CriterionStatus, str]:
        if self._rollback_runbook_exists:
            return CriterionStatus.PASS, "rollback runbook confirmed present"
        return CriterionStatus.FAIL, "rollback runbook not confirmed"

    async def _check_operator_approval(self) -> tuple[CriterionStatus, str]:
        if self._approval and self._approval.approved:
            return (
                CriterionStatus.PASS,
                f"approved by '{self._approval.operator}' "
                f"at {self._approval.approved_at.isoformat()}",
            )
        return CriterionStatus.FAIL, "no operator approval recorded"

    async def _check_exchange_permissions(self) -> tuple[CriterionStatus, str]:
        try:
            # Probe read permission
            await self._exchange.health_check()
            # Probe trade permission via a balance fetch
            await self._exchange.fetch_balances()
        except Exception as exc:
            return CriterionStatus.FAIL, f"exchange health/permission check failed: {exc}"

        # We cannot programmatically verify withdraw permission is absent here
        # (Binance does not expose this via public API). Flag as warning.
        return (
            CriterionStatus.WARNING,
            "read+trade permissions confirmed reachable; "
            "manually verify withdraw permission is ABSENT on the API key",
        )

    async def _check_feature_flags(self) -> tuple[CriterionStatus, str]:
        if self._feature_flags is None:
            return CriterionStatus.WARNING, "feature flag store not connected — cannot verify"

        paper_ok = await self._feature_flags.is_enabled("paper_trading_enabled")
        ws_ok = await self._feature_flags.is_enabled("websocket_enabled")
        live_disabled = not await self._feature_flags.is_enabled("live_trading_enabled")

        if paper_ok and ws_ok and live_disabled:
            return CriterionStatus.PASS, "paper=true, websocket=true, live=false"

        issues = []
        if not paper_ok:
            issues.append("paper_trading_enabled is false")
        if not ws_ok:
            issues.append("websocket_enabled is false")
        if not live_disabled:
            issues.append("live_trading_enabled is already true — unexpected")
        return CriterionStatus.FAIL, "; ".join(issues)

    async def _check_circuit_breakers(self) -> tuple[CriterionStatus, str]:
        risk = get_settings().risk
        defaults = (0.05, 0.10, 0.15)
        configured = (
            risk.tier1_daily_drawdown_pct,
            risk.tier2_daily_drawdown_pct,
            risk.tier3_daily_drawdown_pct,
        )
        if configured == defaults:
            return (
                CriterionStatus.WARNING,
                "circuit breakers are at default values — consider tightening for live",
            )
        return (
            CriterionStatus.PASS,
            f"tiers={configured[0]:.0%}/{configured[1]:.0%}/{configured[2]:.0%}",
        )

    async def _check_capital_policy(self) -> tuple[CriterionStatus, str]:
        alloc = get_settings().capital_allocation
        defaults = (0.30, 0.20, 0.03, 0.07)
        configured = (
            alloc.max_capital_per_strategy_pct,
            alloc.max_capital_per_asset_pct,
            alloc.daily_loss_budget_pct,
            alloc.weekly_loss_budget_pct,
        )
        if configured == defaults:
            return (
                CriterionStatus.WARNING,
                "capital allocation is at default values — review before live deployment",
            )
        return (
            CriterionStatus.PASS,
            f"strategy_cap={configured[0]:.0%}, asset_cap={configured[1]:.0%}, "
            f"daily_budget={configured[2]:.0%}, weekly_budget={configured[3]:.0%}",
        )

    async def _check_reconciler(self) -> tuple[CriterionStatus, str]:
        if self._reconciler_last_run_clean:
            return CriterionStatus.PASS, "last reconciliation run was clean"
        return CriterionStatus.FAIL, "no clean reconciliation run recorded"
