"""Tests for execution/post_trade.py — PostTradeProcessor."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from trading_bot.core.models import OrderSide
from trading_bot.execution.post_trade import FillDetails, FinalizeStep, PostTradeProcessor


def _fill(**kwargs: object) -> FillDetails:
    defaults = {
        "client_order_id": "CLIENT-001",
        "exchange_order_id": "EXCH-001",
        "symbol": "BTC/USDT",
        "side": OrderSide.BUY,
        "strategy_id": "sma",
        "environment": "paper",
        "requested_qty": Decimal("0.001"),
        "filled_qty": Decimal("0.001"),
        "fill_price": Decimal("50000"),
        "fee_paid": Decimal("0.05"),
        "slippage_cost": Decimal("0.25"),
        "exchange_timestamp": datetime.now(UTC),
    }
    defaults.update(kwargs)
    return FillDetails(**defaults)  # type: ignore[arg-type]


class TestPostTradeProcessor:
    @pytest.mark.asyncio
    async def test_no_dependencies_succeeds(self) -> None:
        processor = PostTradeProcessor()
        result = await processor.finalize(_fill())
        assert result.success
        assert FinalizeStep.DUPLICATE_CHECK in result.steps_completed

    @pytest.mark.asyncio
    async def test_all_steps_run_with_no_deps(self) -> None:
        processor = PostTradeProcessor()
        result = await processor.finalize(_fill())
        expected_steps = {
            FinalizeStep.DUPLICATE_CHECK,
            FinalizeStep.OMS_UPDATE,
            FinalizeStep.PORTFOLIO_UPDATE,
            FinalizeStep.ACCOUNTING_UPDATE,
            FinalizeStep.TCA_RECORD,
            FinalizeStep.AUDIT_APPEND,
            FinalizeStep.METRICS_EMIT,
            FinalizeStep.RECONCILE,
        }
        assert expected_steps.issubset(set(result.steps_completed))

    @pytest.mark.asyncio
    async def test_oms_update_called(self) -> None:
        recorded = []

        class FakeOMS:
            def record(self, state: object) -> None:
                recorded.append(state)

        processor = PostTradeProcessor(oms=FakeOMS())
        await processor.finalize(_fill())
        assert len(recorded) == 1

    @pytest.mark.asyncio
    async def test_audit_log_called(self) -> None:
        appended = []

        class FakeAudit:
            async def append(self, **kwargs: object) -> str:
                appended.append(kwargs)
                return "hash"

        processor = PostTradeProcessor(audit_log=FakeAudit())
        await processor.finalize(_fill())
        assert len(appended) == 1
        assert appended[0]["event_type"] == "ORDER_FILLED"

    @pytest.mark.asyncio
    async def test_duplicate_fill_detected_stops_pipeline(self) -> None:
        class FakeIdemStore:
            async def acquire(self, key: str, ttl_seconds: int = 604800) -> bool:
                return False  # simulate duplicate

        processor = PostTradeProcessor(idempotency_store=FakeIdemStore())
        result = await processor.finalize(_fill())
        assert result.success
        assert result.is_duplicate
        # OMS update should NOT have been called (pipeline stopped)
        assert FinalizeStep.OMS_UPDATE not in result.steps_completed

    @pytest.mark.asyncio
    async def test_fill_notional(self) -> None:
        fill = _fill(filled_qty=Decimal("0.001"), fill_price=Decimal("50000"))
        assert fill.fill_notional == Decimal("50")

    @pytest.mark.asyncio
    async def test_is_complete_fill(self) -> None:
        full = _fill(is_partial=False, filled_qty=Decimal("0.001"))
        partial = _fill(is_partial=True, filled_qty=Decimal("0.0005"))
        assert full.is_complete_fill
        assert not partial.is_complete_fill

    @pytest.mark.asyncio
    async def test_partial_fill_oms_uses_partially_filled_status(self) -> None:
        from trading_bot.core.models import OrderStatus

        recorded_statuses = []

        class FakeOMS:
            def record(self, state: object) -> None:
                recorded_statuses.append(state.status)

        processor = PostTradeProcessor(oms=FakeOMS())
        await processor.finalize(_fill(is_partial=True))
        assert OrderStatus.PARTIALLY_FILLED in recorded_statuses
