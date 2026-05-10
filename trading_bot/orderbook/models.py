"""Order book data contracts — #3 of the production readiness roadmap.

These models are the ONLY representation of order book state in the system.
Real provider integration is a TODO — see ROADMAP.md Area #3.

For live/micro-live: fail closed if OrderBook.is_stale() or provider is None.
For paper trading: optional; missing book falls back to WebSocket mid-price.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class OrderBookQuality(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class StaleQuoteError(Exception):
    """Raised when an order book quote is too old for live trading."""


@dataclass(frozen=True)
class OrderBookLevel:
    """A single price level in the order book."""

    price: Decimal
    quantity: Decimal

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity


@dataclass
class OrderBook:
    """Snapshot of a symbol's order book at a point in time.

    bids: sorted descending by price (best bid first).
    asks: sorted ascending by price (best ask first).
    """

    symbol: str
    exchange: str
    bids: list[OrderBookLevel]  # sorted: best bid first (highest price)
    asks: list[OrderBookLevel]  # sorted: best ask first (lowest price)
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Stale threshold — orders in live/micro-live must not use books older than this
    stale_threshold_ms: int = 500

    @property
    def best_bid(self) -> Decimal | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / Decimal("2")

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    @property
    def spread_bps(self) -> Decimal | None:
        if self.spread is None or self.mid_price is None or self.mid_price == 0:
            return None
        return (self.spread / self.mid_price) * Decimal("10000")

    @property
    def quote_age_ms(self) -> float:
        now = datetime.now(UTC)
        return (now - self.received_at).total_seconds() * 1000

    @property
    def quality(self) -> OrderBookQuality:
        if not self.bids or not self.asks:
            return OrderBookQuality.UNAVAILABLE
        if self.quote_age_ms > self.stale_threshold_ms:
            return OrderBookQuality.STALE
        return OrderBookQuality.FRESH

    def is_stale(self) -> bool:
        return self.quality != OrderBookQuality.FRESH

    def bid_depth(self, levels: int = 5) -> list[OrderBookLevel]:
        return self.bids[:levels]

    def ask_depth(self, levels: int = 5) -> list[OrderBookLevel]:
        return self.asks[:levels]

    def bid_volume(self, levels: int = 5) -> Decimal:
        return sum((lvl.quantity for lvl in self.bid_depth(levels)), Decimal("0"))

    def ask_volume(self, levels: int = 5) -> Decimal:
        return sum((lvl.quantity for lvl in self.ask_depth(levels)), Decimal("0"))

    def volume_imbalance(self, levels: int = 5) -> Decimal | None:
        """Positive = buy pressure, negative = sell pressure. Range [-1, 1]."""
        bv = self.bid_volume(levels)
        av = self.ask_volume(levels)
        total = bv + av
        if total == 0:
            return None
        return (bv - av) / total

    def estimated_market_impact_bps(self, order_qty: Decimal, is_buy: bool) -> Decimal | None:
        """Estimate price impact of a market order by walking the book.

        Returns basis points of price movement beyond mid-price. Returns None if
        the book does not have enough depth to fill the order.
        """
        if self.mid_price is None or self.mid_price == 0:
            return None

        levels = self.asks if is_buy else self.bids
        remaining = order_qty
        total_cost = Decimal("0")

        for level in levels:
            fill = min(remaining, level.quantity)
            total_cost += fill * level.price
            remaining -= fill
            if remaining <= 0:
                break

        if remaining > 0:
            return None  # not enough depth

        filled = order_qty - remaining
        if filled == 0:
            return None
        avg_price = total_cost / filled
        return ((avg_price - self.mid_price) / self.mid_price * Decimal("10000")).copy_abs()

    def assert_fresh(self) -> None:
        """Raise StaleQuoteError if the book is stale. Use in pre-trade checks."""
        if self.is_stale():
            raise StaleQuoteError(
                f"order book for {self.symbol} is stale "
                f"(age={self.quote_age_ms:.0f}ms > threshold={self.stale_threshold_ms}ms)"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "best_bid": str(self.best_bid) if self.best_bid else None,
            "best_ask": str(self.best_ask) if self.best_ask else None,
            "mid_price": str(self.mid_price) if self.mid_price else None,
            "spread_bps": str(self.spread_bps) if self.spread_bps else None,
            "quote_age_ms": self.quote_age_ms,
            "quality": self.quality,
        }


class OrderBookProvider(ABC):
    """Abstract provider for real-time order book data.

    TODO (ROADMAP Area #3): Implement for Binance WebSocket depth stream.
    For paper trading: optional — return None if unavailable.
    For live/micro-live: REQUIRED — None causes pre-trade check to FAIL CLOSED.
    """

    @abstractmethod
    async def get_book(self, symbol: str) -> OrderBook | None:
        """Return the latest order book snapshot, or None if unavailable."""

    @abstractmethod
    async def subscribe(self, symbol: str) -> None:
        """Subscribe to real-time updates for a symbol."""

    @abstractmethod
    async def unsubscribe(self, symbol: str) -> None:
        """Unsubscribe from updates."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider stream is healthy."""
