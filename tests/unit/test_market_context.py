"""Unit tests for trading_bot.market_context.

All HTTP calls are mocked — no real API requests.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.market_context import MarketContext
from trading_bot.market_context.fear_greed import FearGreedProvider
from trading_bot.market_context.funding_rate import FundingRateProvider
from trading_bot.market_context.macro import MacroProvider

# ── MarketContext dataclass ───────────────────────────────────────────────────


def _ctx(**kwargs) -> MarketContext:
    defaults = {
        "fear_greed_value": None,
        "fear_greed_label": None,
        "funding_rate": None,
        "fed_funds_rate": None,
        "cpi_yoy": None,
        "fetched_at": datetime.now(UTC),
    }
    return MarketContext(**{**defaults, **kwargs})


class TestMarketContextHelpers:
    def test_extreme_fear(self):
        assert _ctx(fear_greed_value=10).is_extreme_fear() is True
        assert _ctx(fear_greed_value=25).is_extreme_fear() is True
        assert _ctx(fear_greed_value=26).is_extreme_fear() is False
        assert _ctx(fear_greed_value=None).is_extreme_fear() is False

    def test_extreme_greed(self):
        assert _ctx(fear_greed_value=90).is_extreme_greed() is True
        assert _ctx(fear_greed_value=75).is_extreme_greed() is True
        assert _ctx(fear_greed_value=74).is_extreme_greed() is False
        assert _ctx(fear_greed_value=None).is_extreme_greed() is False

    def test_negative_funding(self):
        assert _ctx(funding_rate=-0.0001).is_negative_funding() is True
        assert _ctx(funding_rate=0.0).is_negative_funding() is False
        assert _ctx(funding_rate=0.0001).is_negative_funding() is False
        assert _ctx(funding_rate=None).is_negative_funding() is False

    def test_high_rates(self):
        assert _ctx(fed_funds_rate=5.0).is_high_rates() is True
        assert _ctx(fed_funds_rate=4.0).is_high_rates() is True
        assert _ctx(fed_funds_rate=3.9).is_high_rates() is False
        assert _ctx(fed_funds_rate=None).is_high_rates() is False

    def test_high_inflation(self):
        assert _ctx(cpi_yoy=5.5).is_high_inflation() is True
        assert _ctx(cpi_yoy=4.0).is_high_inflation() is True
        assert _ctx(cpi_yoy=3.9).is_high_inflation() is False
        assert _ctx(cpi_yoy=None).is_high_inflation() is False

    def test_as_dict_contains_all_fields(self):
        ctx = _ctx(fear_greed_value=42, fear_greed_label="Fear", funding_rate=0.0001)
        d = ctx.as_dict()
        assert d["fear_greed_value"] == 42
        assert d["fear_greed_label"] == "Fear"
        assert d["funding_rate"] == 0.0001
        assert "fetched_at" in d


# ── FearGreedProvider ─────────────────────────────────────────────────────────


class TestFearGreedProvider:
    @pytest.mark.asyncio
    async def test_fetch_success(self):
        provider = FearGreedProvider()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [{"value": "23", "value_classification": "Extreme Fear"}]
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch(
            "trading_bot.market_context.fear_greed.httpx.AsyncClient", return_value=mock_client
        ):
            value, label = await provider.fetch()

        assert value == 23
        assert label == "Extreme Fear"

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_none(self):
        provider = FearGreedProvider()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("network error"))

        with patch(
            "trading_bot.market_context.fear_greed.httpx.AsyncClient", return_value=mock_client
        ):
            value, label = await provider.fetch()

        assert value is None
        assert label is None

    @pytest.mark.asyncio
    async def test_ttl_cache_skips_second_request(self):
        provider = FearGreedProvider()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [{"value": "50", "value_classification": "Neutral"}]
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch(
            "trading_bot.market_context.fear_greed.httpx.AsyncClient", return_value=mock_client
        ):
            await provider.fetch()
            await provider.fetch()

        assert mock_client.get.call_count == 1


# ── FundingRateProvider ───────────────────────────────────────────────────────


class TestFundingRateProvider:
    @pytest.mark.asyncio
    async def test_fetch_positive_rate(self):
        provider = FundingRateProvider()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"symbol": "BTCUSDT", "lastFundingRate": "0.00010000"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch(
            "trading_bot.market_context.funding_rate.httpx.AsyncClient", return_value=mock_client
        ):
            rate = await provider.fetch()

        assert rate == pytest.approx(0.0001)

    @pytest.mark.asyncio
    async def test_fetch_negative_rate(self):
        provider = FundingRateProvider()
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"symbol": "BTCUSDT", "lastFundingRate": "-0.00050000"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch(
            "trading_bot.market_context.funding_rate.httpx.AsyncClient", return_value=mock_client
        ):
            rate = await provider.fetch()

        assert rate == pytest.approx(-0.0005)

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_none(self):
        provider = FundingRateProvider()
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("timeout"))

        with patch(
            "trading_bot.market_context.funding_rate.httpx.AsyncClient", return_value=mock_client
        ):
            rate = await provider.fetch()

        assert rate is None


# ── MacroProvider ─────────────────────────────────────────────────────────────


class TestMacroProvider:
    @pytest.mark.asyncio
    async def test_fetch_skipped_without_key(self):
        provider = MacroProvider(api_key="")
        fed_rate, cpi_yoy = await provider.fetch()
        assert fed_rate is None
        assert cpi_yoy is None

    @pytest.mark.asyncio
    async def test_fetch_fed_rate(self):
        provider = MacroProvider(api_key="test_key")

        fed_obs = {"observations": [{"value": "5.33"}]}
        cpi_obs = {"observations": [{"value": str(310 + i)} for i in range(13)]}

        responses = [MagicMock(), MagicMock()]
        responses[0].raise_for_status = MagicMock()
        responses[0].json.return_value = fed_obs
        responses[1].raise_for_status = MagicMock()
        responses[1].json.return_value = cpi_obs

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=responses)

        with patch("trading_bot.market_context.macro.httpx.AsyncClient", return_value=mock_client):
            fed_rate, cpi_yoy = await provider.fetch()

        assert fed_rate == pytest.approx(5.33)
        assert cpi_yoy is not None

    @pytest.mark.asyncio
    async def test_cpi_yoy_calculation(self):
        provider = MacroProvider(api_key="test_key")

        # latest=322, year_ago=310 → YoY = (322/310 - 1) * 100 ≈ 3.87%
        cpi_values = [{"value": str(322 - i)} for i in range(13)]
        fed_obs = {"observations": [{"value": "5.0"}]}
        cpi_obs = {"observations": cpi_values}

        responses = [MagicMock(), MagicMock()]
        responses[0].raise_for_status = MagicMock()
        responses[0].json.return_value = fed_obs
        responses[1].raise_for_status = MagicMock()
        responses[1].json.return_value = cpi_obs

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=responses)

        with patch("trading_bot.market_context.macro.httpx.AsyncClient", return_value=mock_client):
            _, cpi_yoy = await provider.fetch()

        expected = round((322 / 310 - 1) * 100, 2)
        assert cpi_yoy == pytest.approx(expected, rel=1e-3)
