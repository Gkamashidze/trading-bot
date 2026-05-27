"""Tests for trading_bot/market_context/funding_rate.py — Binance ban safety."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.exchange import rate_limit
from trading_bot.market_context.funding_rate import FundingRateProvider


@pytest.fixture(autouse=True)
def reset_circuits() -> None:
    rate_limit.configure_state_store(None)
    rate_limit._circuits.clear()
    rate_limit._request_locks.clear()


def _mock_response(status_code: int, text: str = "", json_data: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.json = MagicMock(return_value=json_data or {})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = Exception(f"HTTP {status_code}")
    return resp


@pytest.mark.asyncio
async def test_skips_call_when_circuit_open() -> None:
    """If Binance ban is active, fetch must not make any network call."""
    future_ms = int(time.time() * 1000) + 60_000  # 1 min in future
    rate_limit.trip_circuit("binance", future_ms)

    provider = FundingRateProvider()
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock()

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await provider.fetch()

    assert result is None
    mock_client.get.assert_not_called()


@pytest.mark.asyncio
async def test_418_response_trips_shared_circuit() -> None:
    """A 418 banned-until response must populate the shared circuit breaker."""
    banned_until = int(time.time() * 1000) + 30_000
    body = (
        f'{{"code":-1003,"msg":"Way too many requests; IP(1.2.3.4) banned until {banned_until}"}}'
    )
    mock_resp = _mock_response(418, text=body)
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    provider = FundingRateProvider()
    with patch("httpx.AsyncClient", return_value=mock_client):
        await provider.fetch()

    # Circuit must now be open
    assert rate_limit.check_circuit("binance") > 0


@pytest.mark.asyncio
async def test_429_response_sets_shared_retry_after_cooldown() -> None:
    """A rate-limit response must pause other Binance REST operations."""
    mock_resp = _mock_response(429, text="too many requests")
    mock_resp.headers = {"Retry-After": "120"}
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    provider = FundingRateProvider()
    with patch("httpx.AsyncClient", return_value=mock_client):
        await provider.fetch()

    assert rate_limit.check_rate_limit_cooldown("binance") >= 118


@pytest.mark.asyncio
async def test_failure_caches_for_one_hour() -> None:
    """Non-ban failures must cache None for 1h to avoid retry-storms."""
    mock_resp = _mock_response(500, text="server error")
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    provider = FundingRateProvider()
    with patch("httpx.AsyncClient", return_value=mock_client):
        await provider.fetch()

    # Cache expiry should be ~1 hour in the future
    assert provider._expires_at is not None
    diff_seconds = (provider._expires_at - datetime.now(UTC)).total_seconds()
    assert 3500 < diff_seconds <= 3600


@pytest.mark.asyncio
async def test_successful_fetch_caches_until_next_settlement() -> None:
    mock_resp = _mock_response(200, json_data={"lastFundingRate": "0.0001"})
    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_resp)

    provider = FundingRateProvider()
    with patch("httpx.AsyncClient", return_value=mock_client):
        rate = await provider.fetch()

    assert rate == 0.0001
    assert provider._expires_at is not None
    # Expiry is one of the 8h settlement windows in the future
    assert provider._expires_at > datetime.now(UTC)


@pytest.mark.asyncio
async def test_cache_hit_skips_network() -> None:
    """If cache is fresh, no network call should be made."""
    provider = FundingRateProvider()
    provider._rate = 0.0002
    provider._expires_at = datetime.now(UTC).replace(year=2099)  # far future

    mock_client = MagicMock()
    mock_client.get = AsyncMock()
    with patch("httpx.AsyncClient", return_value=mock_client):
        rate = await provider.fetch()

    assert rate == 0.0002
    mock_client.get.assert_not_called()
