"""Unit tests for the Go-Live Readiness Gate."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_bot.go_live.criteria import CriterionStatus, ReadinessReport
from trading_bot.go_live.gate import GoLiveGate

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_audit_log() -> AsyncMock:
    audit = AsyncMock()
    audit.append.return_value = "deadbeef"
    return audit


@pytest.fixture
def mock_exchange() -> AsyncMock:
    exchange = AsyncMock()
    exchange.health_check.return_value = True
    exchange.fetch_balances.return_value = {"USDT": Decimal("10000")}
    return exchange


def _full_gate(
    audit_log: AsyncMock,
    exchange: AsyncMock,
    feature_flags: AsyncMock | None = None,
) -> GoLiveGate:
    """A gate configured to PASS all criteria."""
    return GoLiveGate(
        audit_log=audit_log,
        exchange=exchange,
        feature_flags=feature_flags,
        reconciler_last_run_clean=True,
        paper_trading_days=10,
        paper_win_rate=0.55,
        paper_drawdown_pct=0.08,
        backtest_win_rate=0.60,
        backtest_drawdown_pct=0.10,
        risk_sign_off_by="alice",
        rollback_runbook_exists=True,
    )


# ---------------------------------------------------------------------------
# Evaluate — all pass
# ---------------------------------------------------------------------------


class TestGoLiveGateAllPass:
    @pytest.mark.asyncio
    async def test_report_not_ready_without_operator_approval(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        flags = AsyncMock()
        flags.is_enabled.side_effect = lambda name: {
            "paper_trading_enabled": True,
            "websocket_enabled": True,
            "live_trading_enabled": False,
        }.get(name, False)

        gate = _full_gate(mock_audit_log, mock_exchange, flags)
        report = await gate.evaluate()
        # All criteria pass, but no operator approval yet
        assert not report.ready
        assert report.failed_blocking  # operator_approval criterion fails

    @pytest.mark.asyncio
    async def test_ready_after_operator_approval(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        flags = AsyncMock()
        flags.is_enabled.side_effect = lambda name: {
            "paper_trading_enabled": True,
            "websocket_enabled": True,
            "live_trading_enabled": False,
        }.get(name, False)

        gate = _full_gate(mock_audit_log, mock_exchange, flags)
        await gate.record_approval(
            operator="alice",
            comment="reviewed and approved",
            rollback_plan_confirmed=True,
            risk_sign_off_by="alice",
        )
        report = await gate.evaluate()
        assert report.ready, (
            f"Expected ready, failed: {[r.criterion_id for r in report.failed_blocking]}"
        )

    @pytest.mark.asyncio
    async def test_audit_log_called_on_evaluate(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = _full_gate(mock_audit_log, mock_exchange)
        await gate.evaluate()
        mock_audit_log.append.assert_called()


# ---------------------------------------------------------------------------
# Individual criterion failures
# ---------------------------------------------------------------------------


class TestDryRunCriterion:
    @pytest.mark.asyncio
    async def test_fails_when_paper_days_insufficient(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(
            audit_log=mock_audit_log,
            exchange=mock_exchange,
            paper_trading_days=3,  # < 7
        )
        report = await gate.evaluate()
        dry_run = next(r for r in report.results if r.criterion_id == "dry_run_completed")
        assert dry_run.status == CriterionStatus.FAIL
        assert "7" in dry_run.detail

    @pytest.mark.asyncio
    async def test_passes_with_sufficient_days(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(
            audit_log=mock_audit_log,
            exchange=mock_exchange,
            paper_trading_days=14,
        )
        report = await gate.evaluate()
        dry_run = next(r for r in report.results if r.criterion_id == "dry_run_completed")
        assert dry_run.status == CriterionStatus.PASS


class TestPaperParityCriterion:
    @pytest.mark.asyncio
    async def test_fails_when_paper_win_rate_too_low(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(
            audit_log=mock_audit_log,
            exchange=mock_exchange,
            paper_trading_days=10,
            paper_win_rate=0.30,  # 50% of 0.60 = 0.36 → 0.30 < 0.48
            paper_drawdown_pct=0.08,
            backtest_win_rate=0.60,
            backtest_drawdown_pct=0.10,
        )
        report = await gate.evaluate()
        parity = next(r for r in report.results if r.criterion_id == "paper_live_parity")
        assert parity.status == CriterionStatus.FAIL
        assert "win_rate" in parity.detail

    @pytest.mark.asyncio
    async def test_fails_when_drawdown_too_large(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(
            audit_log=mock_audit_log,
            exchange=mock_exchange,
            paper_trading_days=10,
            paper_win_rate=0.55,
            paper_drawdown_pct=0.15,  # > 0.10 * 1.20 = 0.12
            backtest_win_rate=0.60,
            backtest_drawdown_pct=0.10,
        )
        report = await gate.evaluate()
        parity = next(r for r in report.results if r.criterion_id == "paper_live_parity")
        assert parity.status == CriterionStatus.FAIL
        assert "drawdown" in parity.detail

    @pytest.mark.asyncio
    async def test_fails_when_metrics_not_provided(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(audit_log=mock_audit_log, exchange=mock_exchange)
        report = await gate.evaluate()
        parity = next(r for r in report.results if r.criterion_id == "paper_live_parity")
        assert parity.status == CriterionStatus.FAIL


class TestRiskSignOff:
    @pytest.mark.asyncio
    async def test_fails_without_sign_off(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(audit_log=mock_audit_log, exchange=mock_exchange)
        report = await gate.evaluate()
        sign_off = next(r for r in report.results if r.criterion_id == "risk_sign_off")
        assert sign_off.status == CriterionStatus.FAIL

    @pytest.mark.asyncio
    async def test_passes_with_sign_off(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(
            audit_log=mock_audit_log,
            exchange=mock_exchange,
            risk_sign_off_by="bob",
        )
        report = await gate.evaluate()
        sign_off = next(r for r in report.results if r.criterion_id == "risk_sign_off")
        assert sign_off.status == CriterionStatus.PASS
        assert "bob" in sign_off.detail


class TestRollbackPlan:
    @pytest.mark.asyncio
    async def test_fails_without_runbook(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(
            audit_log=mock_audit_log,
            exchange=mock_exchange,
            rollback_runbook_exists=False,
        )
        report = await gate.evaluate()
        rollback = next(r for r in report.results if r.criterion_id == "rollback_plan_present")
        assert rollback.status == CriterionStatus.FAIL

    @pytest.mark.asyncio
    async def test_passes_with_runbook(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(
            audit_log=mock_audit_log,
            exchange=mock_exchange,
            rollback_runbook_exists=True,
        )
        report = await gate.evaluate()
        rollback = next(r for r in report.results if r.criterion_id == "rollback_plan_present")
        assert rollback.status == CriterionStatus.PASS


class TestReconcilerCriterion:
    @pytest.mark.asyncio
    async def test_fails_when_reconciler_not_clean(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(
            audit_log=mock_audit_log,
            exchange=mock_exchange,
            reconciler_last_run_clean=False,
        )
        report = await gate.evaluate()
        rec = next(r for r in report.results if r.criterion_id == "reconciler_healthy")
        assert rec.status == CriterionStatus.FAIL

    @pytest.mark.asyncio
    async def test_passes_when_reconciler_clean(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(
            audit_log=mock_audit_log,
            exchange=mock_exchange,
            reconciler_last_run_clean=True,
        )
        report = await gate.evaluate()
        rec = next(r for r in report.results if r.criterion_id == "reconciler_healthy")
        assert rec.status == CriterionStatus.PASS


# ---------------------------------------------------------------------------
# Operator approval
# ---------------------------------------------------------------------------


class TestOperatorApproval:
    @pytest.mark.asyncio
    async def test_approval_requires_non_empty_operator(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(audit_log=mock_audit_log, exchange=mock_exchange)
        with pytest.raises(ValueError, match="operator"):
            await gate.record_approval(operator="")

    @pytest.mark.asyncio
    async def test_approval_persisted_to_audit_log(
        self, mock_audit_log: AsyncMock, mock_exchange: AsyncMock
    ) -> None:
        gate = GoLiveGate(audit_log=mock_audit_log, exchange=mock_exchange)
        approval = await gate.record_approval(operator="charlie", comment="LGTM")
        assert approval.operator == "charlie"
        assert approval.approved is True
        # Should have been called for both evaluate() inside record_approval and the approval event
        assert mock_audit_log.append.call_count >= 2


# ---------------------------------------------------------------------------
# ReadinessReport helpers
# ---------------------------------------------------------------------------


class TestReadinessReportSummary:
    def test_summary_contains_status(self) -> None:
        from trading_bot.go_live.criteria import CriterionResult

        results = [
            CriterionResult(
                criterion_id="dry_run_completed",
                label="Dry-run",
                status=CriterionStatus.PASS,
                blocking=True,
            )
        ]
        report = ReadinessReport(results=results)
        summary = report.summary()
        assert "NOT READY" in summary  # no operator approval

    def test_not_ready_without_approval_even_if_all_pass(self) -> None:
        from trading_bot.go_live.criteria import CriterionResult

        results = [
            CriterionResult(
                criterion_id=c.criterion_id,
                label=c.label,
                status=CriterionStatus.PASS,
                blocking=c.blocking,
            )
            for c in __import__(
                "trading_bot.go_live.criteria", fromlist=["STANDARD_CRITERIA"]
            ).STANDARD_CRITERIA
        ]
        report = ReadinessReport(results=results, operator_approval=None)
        assert not report.ready
