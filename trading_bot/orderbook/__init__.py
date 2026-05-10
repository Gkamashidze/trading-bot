"""Order book data contracts and provider interface.

Real order book data is REQUIRED for micro-live and live order placement.
For paper trading it is optional — missing book → fall back to WebSocket mid-price.
For live/micro-live — fail closed if no fresh book is available.
"""

from trading_bot.orderbook.models import (
    OrderBook,
    OrderBookLevel,
    OrderBookProvider,
    OrderBookQuality,
    StaleQuoteError,
)

__all__ = [
    "OrderBook",
    "OrderBookLevel",
    "OrderBookProvider",
    "OrderBookQuality",
    "StaleQuoteError",
]
