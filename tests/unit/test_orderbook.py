"""Tests for orderbook/models.py."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_bot.orderbook.models import (
    OrderBook,
    OrderBookLevel,
    OrderBookQuality,
    StaleQuoteError,
)


def _book(age_ms: float = 10.0, threshold_ms: int = 500) -> OrderBook:
    now = datetime.now(UTC) - timedelta(milliseconds=age_ms)
    return OrderBook(
        symbol="BTC/USDT",
        exchange="binance",
        bids=[
            OrderBookLevel(Decimal("49999"), Decimal("2")),
            OrderBookLevel(Decimal("49998"), Decimal("5")),
        ],
        asks=[
            OrderBookLevel(Decimal("50001"), Decimal("1.5")),
            OrderBookLevel(Decimal("50002"), Decimal("3")),
        ],
        received_at=now,
        stale_threshold_ms=threshold_ms,
    )


class TestOrderBook:
    def test_best_bid_and_ask(self) -> None:
        book = _book()
        assert book.best_bid == Decimal("49999")
        assert book.best_ask == Decimal("50001")

    def test_mid_price(self) -> None:
        book = _book()
        assert book.mid_price == Decimal("50000")

    def test_spread(self) -> None:
        book = _book()
        assert book.spread == Decimal("2")

    def test_fresh_book_quality(self) -> None:
        book = _book(age_ms=50)
        assert book.quality == OrderBookQuality.FRESH
        assert not book.is_stale()

    def test_stale_book_quality(self) -> None:
        book = _book(age_ms=1000)
        assert book.quality == OrderBookQuality.STALE
        assert book.is_stale()

    def test_empty_book_is_unavailable(self) -> None:
        book = OrderBook(symbol="X", exchange="x", bids=[], asks=[], received_at=datetime.now(UTC))
        assert book.quality == OrderBookQuality.UNAVAILABLE

    def test_assert_fresh_raises_on_stale(self) -> None:
        book = _book(age_ms=2000)
        with pytest.raises(StaleQuoteError):
            book.assert_fresh()

    def test_assert_fresh_ok_on_fresh(self) -> None:
        book = _book(age_ms=10)
        book.assert_fresh()  # should not raise

    def test_volume_imbalance_buy_pressure(self) -> None:
        book = _book()
        imbalance = book.volume_imbalance(levels=2)
        assert imbalance is not None
        # bids: 2+5=7, asks: 1.5+3=4.5 → imbalance > 0
        assert imbalance > 0

    def test_market_impact_enough_depth(self) -> None:
        book = _book()
        impact = book.estimated_market_impact_bps(Decimal("1"), is_buy=True)
        assert impact is not None
        assert impact >= 0

    def test_market_impact_insufficient_depth(self) -> None:
        book = _book()
        # buy 100 BTC — only 4.5 available in asks
        impact = book.estimated_market_impact_bps(Decimal("100"), is_buy=True)
        assert impact is None

    def test_bid_depth_limited(self) -> None:
        book = _book()
        assert len(book.bid_depth(1)) == 1

    def test_to_dict_has_required_keys(self) -> None:
        d = _book().to_dict()
        assert "symbol" in d
        assert "quality" in d
        assert "spread_bps" in d
