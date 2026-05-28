"""Unit tests for WebSocket price cache and client message parsing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_bot.core.models import PriceTick
from trading_bot.websocket.client import BinanceWebSocketClient
from trading_bot.websocket.price_cache import PriceCache


def _make_tick(symbol: str = "BTCUSDT", price: str = "50000.00") -> PriceTick:
    return PriceTick(
        symbol=symbol,
        price=Decimal(price),
        open_24h=Decimal("48000.00"),
        high_24h=Decimal("51000.00"),
        low_24h=Decimal("47000.00"),
        volume_24h=Decimal("1234.56"),
        timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=UTC),
    )


def _mini_ticker_payload(symbol: str = "BTCUSDT", price: str = "50000.00") -> str:
    return json.dumps(
        {
            "e": "24hrMiniTicker",
            "E": 1705320000000,
            "s": symbol,
            "c": price,
            "o": "48000.00",
            "h": "51000.00",
            "l": "47000.00",
            "v": "1234.56",
            "q": "61728000.00",
        }
    )


class TestPriceCache:
    def test_get_returns_none_for_unknown_symbol(self) -> None:
        cache = PriceCache()
        assert cache.get("BTCUSDT") is None

    @pytest.mark.asyncio
    async def test_update_and_get(self) -> None:
        cache = PriceCache()
        tick = _make_tick()
        await cache.update(tick)
        assert cache.get("BTCUSDT") is tick

    @pytest.mark.asyncio
    async def test_update_overwrites_previous(self) -> None:
        cache = PriceCache()
        await cache.update(_make_tick(price="50000.00"))
        newer = _make_tick(price="51000.00")
        await cache.update(newer)
        assert cache.get("BTCUSDT") is newer

    @pytest.mark.asyncio
    async def test_snapshot_returns_copy(self) -> None:
        cache = PriceCache()
        await cache.update(_make_tick("BTCUSDT"))
        await cache.update(_make_tick("ETHUSDT", price="3000.00"))
        snap = cache.snapshot()
        assert set(snap.keys()) == {"BTCUSDT", "ETHUSDT"}

    def test_change_pct_positive(self) -> None:
        tick = _make_tick(price="50000.00")  # open=48000
        assert tick.change_pct == pytest.approx(4.1667, rel=1e-3)

    def test_change_pct_zero_open(self) -> None:
        tick = PriceTick(
            symbol="BTCUSDT",
            price=Decimal("50000"),
            open_24h=Decimal("0"),
            high_24h=Decimal("51000"),
            low_24h=Decimal("47000"),
            volume_24h=Decimal("1000"),
            timestamp=datetime(2024, 1, 1, tzinfo=UTC),
        )
        assert tick.change_pct == 0.0


class TestBinanceWebSocketClient:
    @pytest.mark.asyncio
    async def test_handle_valid_mini_ticker(self) -> None:
        on_tick = AsyncMock()
        client = BinanceWebSocketClient(symbols=["BTCUSDT"], on_tick=on_tick)
        await client._handle(_mini_ticker_payload())
        on_tick.assert_called_once()
        tick: PriceTick = on_tick.call_args[0][0]
        assert tick.symbol == "BTCUSDT"
        assert tick.price == Decimal("50000.00")

    @pytest.mark.asyncio
    async def test_handle_combined_stream_wrapper(self) -> None:
        on_tick = AsyncMock()
        client = BinanceWebSocketClient(symbols=["BTCUSDT"], on_tick=on_tick)
        wrapped = json.dumps(
            {
                "stream": "btcusdt@miniTicker",
                "data": json.loads(_mini_ticker_payload()),
            }
        )
        await client._handle(wrapped)
        on_tick.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_ignores_unknown_event_type(self) -> None:
        on_tick = AsyncMock()
        client = BinanceWebSocketClient(symbols=["BTCUSDT"], on_tick=on_tick)
        await client._handle(json.dumps({"e": "trade", "s": "BTCUSDT", "p": "50000"}))
        on_tick.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_ignores_malformed_json(self) -> None:
        on_tick = AsyncMock()
        client = BinanceWebSocketClient(symbols=["BTCUSDT"], on_tick=on_tick)
        await client._handle("not-json{{{")
        on_tick.assert_not_called()

    def test_symbol_normalisation(self) -> None:
        client = BinanceWebSocketClient(symbols=["BTC/USDT", "ETH/USDT"], on_tick=AsyncMock())
        assert client._streams == ["btcusdt", "ethusdt"]

    @pytest.mark.asyncio
    async def test_dispatches_kline_payload_to_raw_handler(self) -> None:
        on_tick = AsyncMock()
        on_message = AsyncMock()
        client = BinanceWebSocketClient(
            symbols=["BTC/USDT"],
            on_tick=on_tick,
            extra_streams=["btcusdt@kline_1h"],
            on_message=on_message,
        )
        payload = {"e": "kline", "s": "BTCUSDT", "k": {"x": True}}

        await client._handle(json.dumps({"stream": "btcusdt@kline_1h", "data": payload}))

        on_message.assert_awaited_once_with(payload)
        on_tick.assert_not_called()

    def test_combines_price_and_kline_stream_names(self) -> None:
        client = BinanceWebSocketClient(
            symbols=["BTC/USDT"],
            on_tick=AsyncMock(),
            extra_streams=["btcusdt@kline_1h"],
        )

        assert client._stream_names() == ["btcusdt@miniTicker", "btcusdt@kline_1h"]
