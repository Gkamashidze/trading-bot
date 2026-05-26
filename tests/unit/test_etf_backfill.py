"""Tests for ETF Wave 1 backfill integration.

Verifies:
- Wave 1 ETF symbols are included in backfill candidates (research status)
- SPY / QQQ / SOXX / IBIT resolve to Alpaca venue
- IWM / TLT / GLD are excluded while disabled
- BTC/USDT resolves to Binance
- Lineage source uses the actual exchange (alpaca / binance), not a hardcoded string
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from trading_bot.asset_universe.registry import AssetStatus, get_asset_registry
from trading_bot.core.models import ExchangeId

_WAVE1_ETF_SYMBOLS = {"SPY", "QQQ", "SOXX", "IBIT"}
_FUTURE_WAVE_SYMBOLS = {"IWM", "TLT", "GLD"}


# ── Backfill candidate set ───────────────────────────────────────────────────


class TestBackfillCandidates:
    def test_wave1_etfs_in_all_symbols(self) -> None:
        symbols = get_asset_registry().all_symbols(tradeable_only=False)
        assert _WAVE1_ETF_SYMBOLS.issubset(symbols)

    def test_future_wave_etfs_excluded_from_all_symbols(self) -> None:
        symbols = get_asset_registry().all_symbols(tradeable_only=False)
        assert _FUTURE_WAVE_SYMBOLS.isdisjoint(symbols)

    def test_btc_eth_in_all_symbols(self) -> None:
        symbols = get_asset_registry().all_symbols(tradeable_only=False)
        assert "BTC/USDT" in symbols
        assert "ETH/USDT" in symbols

    def test_wave1_etfs_are_research_status(self) -> None:
        registry = get_asset_registry()
        for sym in _WAVE1_ETF_SYMBOLS:
            spec = registry.get(sym)
            assert spec is not None, f"{sym} missing from registry"
            assert spec.status == AssetStatus.RESEARCH, (
                f"{sym} expected research, got {spec.status}"
            )

    def test_future_wave_etfs_are_disabled(self) -> None:
        registry = get_asset_registry()
        for sym in _FUTURE_WAVE_SYMBOLS:
            spec = registry.get(sym)
            assert spec is not None, f"{sym} missing from registry"
            assert spec.status == AssetStatus.DISABLED, (
                f"{sym} expected disabled, got {spec.status}"
            )

    def test_wave1_etfs_in_etf_symbols_view(self) -> None:
        etf_syms = set(get_asset_registry().etf_symbols(tradeable_only=False))
        assert _WAVE1_ETF_SYMBOLS.issubset(etf_syms)

    def test_future_wave_etfs_not_in_etf_symbols_view(self) -> None:
        etf_syms = set(get_asset_registry().etf_symbols(tradeable_only=False))
        assert _FUTURE_WAVE_SYMBOLS.isdisjoint(etf_syms)


# ── Venue / exchange resolution ──────────────────────────────────────────────


class TestVenueResolution:
    @pytest.mark.parametrize("symbol", sorted(_WAVE1_ETF_SYMBOLS))
    def test_wave1_etf_resolves_to_alpaca(self, symbol: str) -> None:
        spec = get_asset_registry().get(symbol)
        assert spec is not None
        assert spec.venue == ExchangeId.ALPACA, f"{symbol}: expected ALPACA, got {spec.venue}"

    @pytest.mark.parametrize("symbol", ["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    def test_crypto_resolves_to_binance(self, symbol: str) -> None:
        spec = get_asset_registry().get(symbol)
        assert spec is not None
        assert spec.venue == ExchangeId.BINANCE, f"{symbol}: expected BINANCE, got {spec.venue}"

    def test_disabled_etfs_exist_in_registry_but_are_not_data_eligible(self) -> None:
        registry = get_asset_registry()
        for sym in _FUTURE_WAVE_SYMBOLS:
            assert not registry.is_data_eligible(sym), f"{sym} should not be data-eligible"

    def test_wave1_etfs_are_data_eligible(self) -> None:
        registry = get_asset_registry()
        for sym in _WAVE1_ETF_SYMBOLS:
            assert registry.is_data_eligible(sym), f"{sym} should be data-eligible"


# ── Lineage source ───────────────────────────────────────────────────────────


class TestLineageSource:
    """OHLCVDownloader must write the actual exchange name in lineage source."""

    @pytest.mark.asyncio
    async def test_alpaca_lineage_source_for_etf(self, tmp_path: Path) -> None:
        from trading_bot.data.ingestion import OHLCVDownloader

        fake_bar = {
            "open_time": datetime(2025, 1, 2, tzinfo=UTC),
            "open": 500.0,
            "high": 505.0,
            "low": 498.0,
            "close": 502.0,
            "volume": 1_000_000.0,
        }
        exchange_mock = AsyncMock()
        exchange_mock.fetch_ohlcv.return_value = [fake_bar]

        downloader = OHLCVDownloader(exchange=exchange_mock, base_path=tmp_path)
        await downloader.download(
            exchange_id=ExchangeId.ALPACA,
            symbol="SPY",
            timeframe="1d",
            start=datetime(2025, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 3, tzinfo=UTC),
        )

        lineage_files = list(tmp_path.glob("**/*.lineage.json"))  # noqa: ASYNC240
        assert len(lineage_files) == 1, "Expected exactly one lineage file"
        lineage = json.loads(lineage_files[0].read_text())
        assert lineage["source"].startswith("alpaca.fetch_ohlcv"), (
            f"Expected 'alpaca.fetch_ohlcv...', got {lineage['source']!r}"
        )

    @pytest.mark.asyncio
    async def test_binance_lineage_source_for_crypto(self, tmp_path: Path) -> None:
        from trading_bot.data.ingestion import OHLCVDownloader

        fake_bar = {
            "open_time": datetime(2025, 1, 2, tzinfo=UTC),
            "open": 40_000.0,
            "high": 41_000.0,
            "low": 39_000.0,
            "close": 40_500.0,
            "volume": 500.0,
        }
        exchange_mock = AsyncMock()
        exchange_mock.fetch_ohlcv.return_value = [fake_bar]

        downloader = OHLCVDownloader(exchange=exchange_mock, base_path=tmp_path)
        await downloader.download(
            exchange_id=ExchangeId.BINANCE,
            symbol="BTC/USDT",
            timeframe="1d",
            start=datetime(2025, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 3, tzinfo=UTC),
        )

        lineage_files = list(tmp_path.glob("**/*.lineage.json"))  # noqa: ASYNC240
        assert len(lineage_files) == 1, "Expected exactly one lineage file"
        lineage = json.loads(lineage_files[0].read_text())
        assert lineage["source"].startswith("binance.fetch_ohlcv"), (
            f"Expected 'binance.fetch_ohlcv...', got {lineage['source']!r}"
        )

    @pytest.mark.asyncio
    async def test_lineage_source_contains_symbol_and_timeframe(self, tmp_path: Path) -> None:
        from trading_bot.data.ingestion import OHLCVDownloader

        fake_bar = {
            "open_time": datetime(2025, 1, 2, tzinfo=UTC),
            "open": 500.0,
            "high": 505.0,
            "low": 498.0,
            "close": 502.0,
            "volume": 1_000_000.0,
        }
        exchange_mock = AsyncMock()
        exchange_mock.fetch_ohlcv.return_value = [fake_bar]

        downloader = OHLCVDownloader(exchange=exchange_mock, base_path=tmp_path)
        await downloader.download(
            exchange_id=ExchangeId.ALPACA,
            symbol="QQQ",
            timeframe="1d",
            start=datetime(2025, 1, 1, tzinfo=UTC),
            end=datetime(2025, 1, 3, tzinfo=UTC),
        )

        lineage_files = list(tmp_path.glob("**/*.lineage.json"))  # noqa: ASYNC240
        lineage = json.loads(lineage_files[0].read_text())
        assert "QQQ" in lineage["source"]
        assert "1d" in lineage["source"]


# ── Scheduler bootstrap days ─────────────────────────────────────────────────


class TestSchedulerBootstrapDays:
    def test_spy_qqq_soxx_bootstrap_730(self) -> None:
        from trading_bot.scheduler.jobs import _ETF_BOOTSTRAP_DAYS

        assert _ETF_BOOTSTRAP_DAYS["SPY"] == 730
        assert _ETF_BOOTSTRAP_DAYS["QQQ"] == 730
        assert _ETF_BOOTSTRAP_DAYS["SOXX"] == 730

    def test_ibit_bootstrap_365(self) -> None:
        from trading_bot.scheduler.jobs import _ETF_BOOTSTRAP_DAYS

        assert _ETF_BOOTSTRAP_DAYS["IBIT"] == 365

    def test_future_wave_not_in_bootstrap_dict(self) -> None:
        from trading_bot.scheduler.jobs import _ETF_BOOTSTRAP_DAYS

        for sym in _FUTURE_WAVE_SYMBOLS:
            assert sym not in _ETF_BOOTSTRAP_DAYS, f"{sym} should not be in bootstrap dict"
