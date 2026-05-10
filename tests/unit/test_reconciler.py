"""Tests for the OMS <> Exchange Reconciler."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_bot.core.models import ExchangeId, OrderState, OrderStatus
from trading_bot.oms.reconciler import Reconciler
from trading_bot.oms.tracker import OrderTracker
from trading_bot.utils.clock import FakeClock


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock(start=datetime(2024, 1, 1, tzinfo=UTC))


@pytest.fixture
def mock_exchange() -> AsyncMock:
    exchange = AsyncMock()
    exchange.fetch_open_orders.return_value = []
    return exchange


def _open_order(client_id: str = "abc", exchange_id: str | None = None) -> OrderState:
    return OrderState(
        client_order_id=client_id,
        exchange_order_id=exchange_id,
        symbol="BTC/USDT",
        exchange=ExchangeId.BINANCE,
        side="buy",
        order_type="market",
        requested_quantity=Decimal("0.01"),
        status=OrderStatus.OPEN,
    )


class TestReconcilerRunOnce:
    @pytest.mark.asyncio
    async def test_matched_when_both_empty(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("trading_bot.oms.reconciler.get_order_tracker", lambda: OrderTracker())
        r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
        event = await r.run_once()
        assert event.matched is True
        assert event.discrepancies == []

    @pytest.mark.asyncio
    async def test_count_mismatch_detected(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracker = OrderTracker()
        tracker.record(_open_order("o1"))
        monkeypatch.setattr("trading_bot.oms.reconciler.get_order_tracker", lambda: tracker)
        mock_exchange.fetch_open_orders.return_value = []  # exchange sees 0

        r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
        event = await r.run_once()
        assert event.matched is False
        assert len(event.discrepancies) >= 1
        assert r.mismatch_count == 1  # property is on Reconciler, not event

    @pytest.mark.asyncio
    async def test_reconciler_mismatch_count_increments(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracker = OrderTracker()
        tracker.record(_open_order("o1"))
        monkeypatch.setattr("trading_bot.oms.reconciler.get_order_tracker", lambda: tracker)
        mock_exchange.fetch_open_orders.return_value = []

        r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
        await r.run_once()
        await r.run_once()
        assert r.mismatch_count == 2

    @pytest.mark.asyncio
    async def test_ghost_order_detected(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracker = OrderTracker()
        tracker.record(_open_order("c1", exchange_id="EX-999"))
        monkeypatch.setattr("trading_bot.oms.reconciler.get_order_tracker", lambda: tracker)
        mock_exchange.fetch_open_orders.return_value = []  # EX-999 not on exchange

        r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
        event = await r.run_once()
        assert event.matched is False
        assert any("EX-999" in d for d in event.discrepancies)

    @pytest.mark.asyncio
    async def test_run_count_increments(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("trading_bot.oms.reconciler.get_order_tracker", lambda: OrderTracker())
        r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
        await r.run_once()
        await r.run_once()
        assert r.run_count == 2

    @pytest.mark.asyncio
    async def test_last_run_updated(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("trading_bot.oms.reconciler.get_order_tracker", lambda: OrderTracker())
        r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
        assert r.last_run is None
        await r.run_once()
        assert r.last_run == datetime(2024, 1, 1, tzinfo=UTC)

    @pytest.mark.asyncio
    async def test_exchange_error_does_not_raise(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("trading_bot.oms.reconciler.get_order_tracker", lambda: OrderTracker())
        mock_exchange.fetch_open_orders.side_effect = RuntimeError("network failure")
        r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
        event = await r.run_once()  # must not raise
        assert event.exchange_position_count == 0
