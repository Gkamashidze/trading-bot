"""Order Management System — order log with DB persistence.

Singleton via get_order_tracker(). Keeps the most recent N orders in memory
for dashboard display and audit inspection. Orders are also persisted to the
paper_orders table in Postgres so history survives app restarts.

Call init_tracker(pool) in main.py after the DB pool is ready.
"""

from __future__ import annotations

from collections import deque
from decimal import Decimal
from typing import Any

from trading_bot.core.models import OrderState, OrderStatus
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_MAX_ORDERS = 200
_tracker: OrderTracker | None = None


class OrderTracker:
    def __init__(self, max_orders: int = _MAX_ORDERS) -> None:
        self._orders: deque[OrderState] = deque(maxlen=max_orders)
        self._pool: Any = None

    def set_pool(self, pool: Any) -> None:
        self._pool = pool

    def record(self, order: OrderState) -> None:
        self._orders.appendleft(order)
        log.info(
            "order_recorded",
            order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            status=order.status,
        )
        if self._pool is not None:
            import asyncio

            asyncio.create_task(self._persist(order))  # noqa: RUF006

    async def _persist(self, order: OrderState) -> None:
        """Write order to paper_orders table (fire-and-forget, best-effort)."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO paper_orders (
                        order_id, strategy_id, symbol, exchange, side, order_type,
                        requested_qty, filled_qty, fill_price, status, reject_reason
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                    ON CONFLICT (order_id) DO NOTHING
                    """,
                    order.client_order_id,
                    order.strategy_id,
                    order.symbol,
                    str(order.exchange),
                    str(order.side),
                    str(order.order_type),
                    float(order.requested_quantity) if order.requested_quantity else None,
                    float(order.filled_quantity) if order.filled_quantity else None,
                    float(order.average_fill_price) if order.average_fill_price else None,
                    str(order.status),
                    order.reject_reason,
                )
        except Exception as e:
            log.error("order_persist_failed", order_id=order.client_order_id, error=str(e))

    async def load_recent(self, n: int = _MAX_ORDERS) -> None:
        """Rehydrate order deque from DB on startup."""
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT order_id, strategy_id, symbol, exchange, side, order_type,
                           requested_qty, filled_qty, fill_price, status, reject_reason, created_at
                    FROM paper_orders
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    n,
                )
            self._orders.clear()
            for row in reversed(rows):  # oldest first so deque order is newest-first after insert
                try:
                    state = OrderState(
                        client_order_id=row["order_id"],
                        strategy_id=row["strategy_id"] or "",
                        symbol=row["symbol"],
                        exchange=row["exchange"],
                        side=row["side"],
                        order_type=row["order_type"],
                        requested_quantity=Decimal(str(row["requested_qty"] or 0)),
                        filled_quantity=Decimal(str(row["filled_qty"]))
                        if row["filled_qty"]
                        else None,
                        average_fill_price=Decimal(str(row["fill_price"]))
                        if row["fill_price"]
                        else None,
                        status=OrderStatus(row["status"]),
                        reject_reason=row["reject_reason"],
                    )
                    self._orders.appendleft(state)
                except Exception as e:
                    log.warning("order_rehydration_row_failed", error=str(e))
            log.info("order_tracker_rehydrated", count=len(self._orders))
        except Exception as e:
            log.error("order_tracker_load_failed", error=str(e))

    def recent(self, n: int = 20) -> list[OrderState]:
        return list(self._orders)[:n]

    def count(self) -> int:
        return len(self._orders)


def get_order_tracker() -> OrderTracker:
    global _tracker
    if _tracker is None:
        _tracker = OrderTracker()
    return _tracker


def init_tracker(pool: Any) -> OrderTracker:
    """Wire up the DB pool on startup and return the singleton tracker."""
    tracker = get_order_tracker()
    tracker.set_pool(pool)
    return tracker
