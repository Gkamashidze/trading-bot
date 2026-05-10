"""Order Management System — in-memory order log.

Singleton via get_order_tracker(). Keeps the most recent N orders for
display in the dashboard and audit inspection.
"""

from __future__ import annotations

from collections import deque

from trading_bot.core.models import OrderState
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_MAX_ORDERS = 100
_tracker: OrderTracker | None = None


class OrderTracker:
    def __init__(self, max_orders: int = _MAX_ORDERS) -> None:
        self._orders: deque[OrderState] = deque(maxlen=max_orders)

    def record(self, order: OrderState) -> None:
        self._orders.appendleft(order)
        log.info(
            "order_recorded",
            order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side,
            status=order.status,
        )

    def recent(self, n: int = 20) -> list[OrderState]:
        return list(self._orders)[:n]

    def count(self) -> int:
        return len(self._orders)


def get_order_tracker() -> OrderTracker:
    global _tracker
    if _tracker is None:
        _tracker = OrderTracker()
    return _tracker
