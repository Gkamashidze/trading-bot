"""Unit tests for oms/tracker.py — order recording, DB persistence, and rehydration."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from trading_bot.core.models import (
    ExchangeId,
    OrderSide,
    OrderState,
    OrderStatus,
    OrderType,
)
from trading_bot.oms.tracker import OrderTracker


def _make_order(
    order_id: str = "ord-001",
    status: OrderStatus = OrderStatus.FILLED,
) -> OrderState:
    return OrderState(
        client_order_id=order_id,
        symbol="BTC/USDT",
        exchange=ExchangeId.BINANCE,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        requested_quantity=Decimal("0.01"),
        filled_quantity=Decimal("0.01"),
        average_fill_price=Decimal("50000"),
        status=status,
        strategy_id="sma_crossover",
    )


def _make_pool() -> MagicMock:
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=None)
    mock_conn.fetch = AsyncMock(return_value=[])
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_pool


class TestOrderTrackerRecord:
    def test_record_adds_to_deque(self) -> None:
        tracker = OrderTracker()
        order = _make_order()
        tracker.record(order)
        assert tracker.count() == 1
        assert tracker.recent(1)[0].client_order_id == "ord-001"

    def test_record_multiple_orders_newest_first(self) -> None:
        tracker = OrderTracker()
        tracker.record(_make_order("ord-001"))
        tracker.record(_make_order("ord-002"))
        recent = tracker.recent(2)
        assert recent[0].client_order_id == "ord-002"
        assert recent[1].client_order_id == "ord-001"

    def test_deque_respects_max_size(self) -> None:
        tracker = OrderTracker(max_orders=3)
        for i in range(5):
            tracker.record(_make_order(f"ord-{i:03d}"))
        assert tracker.count() == 3

    def test_record_without_pool_does_not_crash(self) -> None:
        tracker = OrderTracker()
        order = _make_order()
        tracker.record(order)  # pool is None — no DB call, no crash
        assert tracker.count() == 1


class TestOrderTrackerLoadRecent:
    async def test_load_recent_rehydrates_from_db(self) -> None:
        pool = _make_pool()
        mock_conn = pool.acquire.return_value.__aenter__.return_value
        mock_conn.fetch = AsyncMock(
            return_value=[
                {
                    "order_id": "ord-db-001",
                    "strategy_id": "sma_crossover",
                    "symbol": "BTC/USDT",
                    "exchange": "binance",
                    "side": "buy",
                    "order_type": "market",
                    "requested_qty": 0.01,
                    "filled_qty": 0.01,
                    "fill_price": 50000.0,
                    "status": "filled",
                    "reject_reason": None,
                    "created_at": None,
                }
            ]
        )
        tracker = OrderTracker()
        tracker.set_pool(pool)

        await tracker.load_recent(n=10)

        assert tracker.count() == 1
        assert tracker.recent(1)[0].client_order_id == "ord-db-001"

    async def test_load_recent_no_pool_is_noop(self) -> None:
        tracker = OrderTracker()
        await tracker.load_recent()
        assert tracker.count() == 0

    async def test_load_recent_empty_db_clears_deque(self) -> None:
        pool = _make_pool()
        tracker = OrderTracker()
        tracker.record(_make_order("ord-stale"))
        tracker.set_pool(pool)

        await tracker.load_recent()

        assert tracker.count() == 0

    async def test_load_recent_db_failure_does_not_crash(self) -> None:
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB timeout")
        )
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        tracker = OrderTracker()
        tracker.set_pool(pool)

        await tracker.load_recent()  # must not raise

        assert tracker.count() == 0


class TestOrderTrackerInitTracker:
    def test_init_tracker_wires_pool(self) -> None:
        from trading_bot.oms.tracker import OrderTracker

        pool = _make_pool()
        tracker = OrderTracker()
        tracker.set_pool(pool)
        assert tracker._pool is pool
