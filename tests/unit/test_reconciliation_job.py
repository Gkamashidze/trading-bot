"""Unit tests for the scheduled reconciliation_job.

Covers:
- runs the reconciler and persists the report to evidence
- skips cleanly when no reconciler is registered
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.oms.reconciler import ReconciliationReport, ReconciliationSeverity
from trading_bot.scheduler.jobs import reconciliation_job


def _clean_report() -> ReconciliationReport:
    return ReconciliationReport(
        severity=ReconciliationSeverity.OK,
        order_discrepancies=[],
        balance_discrepancies=[],
        position_discrepancies=[],
        orders_blocked=False,
        run_at=datetime.now(UTC),
        run_count=1,
        mismatch_count=0,
    )


class TestReconciliationJob:
    @pytest.mark.asyncio
    async def test_runs_and_persists(self) -> None:
        report = _clean_report()
        reconciler = MagicMock()
        reconciler.run_once = AsyncMock(return_value=report)
        record = AsyncMock()

        with (
            patch("trading_bot.oms.reconciler.get_reconciler", return_value=reconciler),
            patch("trading_bot.evidence.recorder.record_reconciliation_evidence", record),
        ):
            await reconciliation_job()

        reconciler.run_once.assert_awaited_once()
        record.assert_awaited_once_with(report)

    @pytest.mark.asyncio
    async def test_skips_when_no_reconciler(self) -> None:
        record = AsyncMock()
        with (
            patch("trading_bot.oms.reconciler.get_reconciler", return_value=None),
            patch("trading_bot.evidence.recorder.record_reconciliation_evidence", record),
        ):
            await reconciliation_job()

        record.assert_not_awaited()
