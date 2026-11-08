"""Incomplete, stale or failed evidence must never authorize real money."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_bot.go_live.criteria import (
    ApprovalEvent,
    CriterionResult,
    CriterionStatus,
    ReadinessReport,
)
from trading_bot.go_live.gate import GoLiveGate


def test_empty_report_and_blocking_warning_are_not_ready() -> None:
    approval = ApprovalEvent(
        operator="alice", approved=True, rollback_plan_confirmed=True, risk_sign_off_by="alice"
    )
    assert not ReadinessReport(results=[], operator_approval=approval).ready
    result = CriterionResult(
        criterion_id="exchange_permissions", label="permissions", status=CriterionStatus.WARNING
    )
    assert not ReadinessReport(results=[result], operator_approval=approval).ready


@pytest.mark.parametrize("age", [timedelta(days=2), timedelta(minutes=-10)])
def test_stale_or_future_operator_approvals_are_not_current(age: timedelta) -> None:
    approval = ApprovalEvent(operator="alice", approved=True, approved_at=datetime.now(UTC) - age)
    assert not approval.is_current


async def test_exchange_false_health_is_a_failure() -> None:
    exchange = AsyncMock()
    exchange.health_check.return_value = False
    gate = GoLiveGate(audit_log=AsyncMock(), exchange=exchange, exchange_permissions_verified=True)
    assert (await gate._check_exchange_permissions())[0] == CriterionStatus.FAIL


async def test_thresholds_cannot_be_lowered_to_zero() -> None:
    gate = GoLiveGate(
        audit_log=AsyncMock(),
        exchange=AsyncMock(),
        min_paper_days=0,
        min_round_trips=0,
        paper_trading_days=1,
        paper_round_trips=1,
    )
    assert (await gate._check_paper_evidence())[0] == CriterionStatus.FAIL


async def test_operator_cannot_approve_failed_technical_gates() -> None:
    gate = GoLiveGate(audit_log=AsyncMock(), exchange=AsyncMock())
    with pytest.raises(ValueError, match="failing readiness"):
        await gate.record_approval(
            operator="alice", rollback_plan_confirmed=True, risk_sign_off_by="alice"
        )
    assert gate._approval is None


async def test_missing_or_unreadable_persistent_risk_state_blocks_trading() -> None:
    from trading_bot.state.risk_state import PostgresRiskStateStore

    conn = AsyncMock()
    conn.fetchrow.return_value = None
    pool = MagicMock()
    pool.acquire.return_value.__aenter__.return_value = conn
    assert (await PostgresRiskStateStore(pool).get_snapshot()).is_trading_globally_blocked
    conn.fetchrow.side_effect = ConnectionError("database unavailable")
    assert (await PostgresRiskStateStore(pool).get_snapshot()).is_trading_globally_blocked
