"""Regression tests for Binance REST ban prevention."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import ccxt.async_support as ccxt
import pytest

from trading_bot.core.exceptions import ExchangeBannedError, ExchangeRateLimitError
from trading_bot.exchange import rate_limit
from trading_bot.exchange.binance import BinanceExchange


@pytest.fixture(autouse=True)
def reset_rate_limit_state() -> None:
    rate_limit.configure_state_store(None)
    rate_limit._circuits.clear()
    rate_limit._request_locks.clear()


def _client() -> MagicMock:
    client = MagicMock()
    client.public_get_klines = AsyncMock()
    client.close = AsyncMock()
    client.last_response_headers = {"X-MBX-USED-WEIGHT-1M": "1"}
    return client


def _raw_bar() -> list[list[object]]:
    return [
        [
            int(datetime(2026, 5, 27, tzinfo=UTC).timestamp() * 1000),
            "100",
            "101",
            "99",
            "100.5",
            "2",
            0,
            "201",
            3,
        ]
    ]


@pytest.mark.asyncio
async def test_fetch_ohlcv_uses_direct_kline_endpoint_without_market_catalog() -> None:
    client = _client()
    client.public_get_klines.return_value = _raw_bar()
    with patch("trading_bot.exchange.binance.ccxt.binance", return_value=client):
        exchange = BinanceExchange(testnet=False)

    result = await exchange.fetch_ohlcv("BTC/USDT", "1h", limit=1000)

    assert len(result) == 1
    client.public_get_klines.assert_awaited_once_with(
        {"symbol": "BTCUSDT", "interval": "1h", "limit": 1000}
    )
    client.load_markets.assert_not_called()


@pytest.mark.asyncio
async def test_first_ban_response_stops_concurrent_queued_request() -> None:
    first_client = _client()
    second_client = _client()
    entered = asyncio.Event()
    banned_until = int(time.time() * 1000) + 600_000

    async def banned_request(_params: dict[str, object]) -> list[list[object]]:
        entered.set()
        await asyncio.sleep(0.01)
        raise ccxt.DDoSProtection(
            f'binance 418 Unknown {{"code":-1003,"msg":"IP banned until {banned_until}"}}'
        )

    first_client.public_get_klines.side_effect = banned_request
    with patch(
        "trading_bot.exchange.binance.ccxt.binance",
        side_effect=[first_client, second_client],
    ):
        first = BinanceExchange(testnet=False)
        second = BinanceExchange(testnet=False)

    first_task = asyncio.create_task(first.fetch_ohlcv("BTC/USDT", "1h"))
    await entered.wait()
    second_task = asyncio.create_task(second.fetch_ohlcv("ETH/USDT", "1h"))
    results = await asyncio.gather(first_task, second_task, return_exceptions=True)

    assert all(isinstance(result, ExchangeBannedError) for result in results)
    first_client.public_get_klines.assert_awaited_once()
    second_client.public_get_klines.assert_not_awaited()


@pytest.mark.asyncio
async def test_ccxt_ddos_429_honors_retry_after_without_second_call() -> None:
    first_client = _client()
    first_client.last_response_headers = {"Retry-After": "120"}
    first_client.public_get_klines.side_effect = ccxt.DDoSProtection(
        'binance 429 Too Many Requests {"code":-1003}'
    )
    second_client = _client()
    with patch(
        "trading_bot.exchange.binance.ccxt.binance",
        side_effect=[first_client, second_client],
    ):
        first = BinanceExchange(testnet=False)
        second = BinanceExchange(testnet=False)

    with pytest.raises(ExchangeRateLimitError):
        await first.fetch_ohlcv("BTC/USDT", "1h")
    with pytest.raises(ExchangeRateLimitError):
        await second.fetch_ohlcv("ETH/USDT", "1h")

    assert rate_limit.check_rate_limit_cooldown("binance") >= 118
    second_client.public_get_klines.assert_not_awaited()
