"""Unit tests for core domain models.

Tests:
- OHLCVBar: UTC enforcement, OHLCV invariants
- OrderRequest: field validation
- Signal: strength bounds
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading_bot.core.models import (
    ExchangeId,
    OHLCVBar,
    OrderRequest,
    OrderSide,
    OrderType,
    Signal,
    PromotionStage,
)


class TestOHLCVBar:
    def _valid_bar(self, **kwargs: object) -> dict:
        base: dict = dict(
            symbol="BTC/USDT",
            exchange=ExchangeId.BINANCE,
            timeframe="1d",
            open_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
            close_time=datetime(2024, 1, 1, 23, 59, 59, tzinfo=timezone.utc),
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("1000"),
            quote_volume=Decimal("50000000"),
        )
        base.update(kwargs)
        return base

    def test_valid_bar_creates_successfully(self) -> None:
        bar = OHLCVBar(**self._valid_bar())
        assert bar.symbol == "BTC/USDT"
        assert bar.close == Decimal("50500")

    def test_naive_open_time_rejected(self) -> None:
        """Naive datetime must be rejected — UTC enforcement."""
        with pytest.raises(ValueError, match="Naive datetime"):
            OHLCVBar(
                **self._valid_bar(
                    open_time=datetime(2024, 1, 1)  # no tzinfo
                )
            )

    def test_high_less_than_low_rejected(self) -> None:
        with pytest.raises(ValueError, match="high.*low"):
            OHLCVBar(**self._valid_bar(high=Decimal("48000"), low=Decimal("49000")))

    def test_open_outside_high_low_rejected(self) -> None:
        with pytest.raises(ValueError, match="open"):
            OHLCVBar(**self._valid_bar(open=Decimal("52000")))  # above high=51000

    def test_negative_volume_rejected(self) -> None:
        with pytest.raises(ValueError, match="volume"):
            OHLCVBar(**self._valid_bar(volume=Decimal("-1")))

    def test_close_time_before_open_time_rejected(self) -> None:
        with pytest.raises(ValueError, match="close_time"):
            OHLCVBar(**self._valid_bar(close_time=datetime(2023, 12, 31, tzinfo=timezone.utc)))


class TestOrderRequest:
    def test_limit_order_without_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="LIMIT order requires limit_price"):
            OrderRequest(
                symbol="BTC/USDT",
                exchange=ExchangeId.BINANCE,
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.001"),
                # limit_price missing
            )

    def test_zero_quantity_rejected(self) -> None:
        with pytest.raises(ValueError, match="quantity must be positive"):
            OrderRequest(
                symbol="BTC/USDT",
                exchange=ExchangeId.BINANCE,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0"),
            )

    def test_valid_market_order(self) -> None:
        req = OrderRequest(
            symbol="BTC/USDT",
            exchange=ExchangeId.BINANCE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.001"),
        )
        assert req.client_order_id  # auto-generated UUID


class TestSignal:
    def test_signal_strength_must_be_0_to_1(self) -> None:
        with pytest.raises(ValueError):
            Signal(
                strategy_id="sma_v1",
                strategy_version="1.0.0",
                promotion_stage=PromotionStage.SHADOW,
                symbol="BTC/USDT",
                exchange=ExchangeId.BINANCE,
                side=OrderSide.BUY,
                strength=1.5,  # out of range
            )
