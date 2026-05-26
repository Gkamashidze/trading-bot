"""Unit tests for OHLCVDownloader — resumable, idempotent, partitioned Parquet."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from trading_bot.core.models import ExchangeId
from trading_bot.data.ingestion import OHLCVDownloader, _next_month


def _make_raw_bars(
    start: datetime,
    count: int,
    symbol: str = "BTC/USDT",
    timeframe: str = "1d",
) -> list[dict]:
    """Return CCXT-shaped raw bar dicts."""
    bars = []
    for i in range(count):
        ts = start + timedelta(days=i)
        price = 50000.0 + i * 100
        bars.append(
            {
                "open_time": ts,
                "open": price,
                "high": price + 500,
                "low": price - 300,
                "close": price + 200,
                "volume": 1000.0,
                "quote_volume": 50_000_000.0,
                "trade_count": 50000,
                "symbol": symbol,
                "exchange": "binance",
                "timeframe": timeframe,
                "source": "binance.fetch_ohlcv",
                "schema_version": "1.0",
                "fetched_at": datetime.now(UTC),
            }
        )
    return bars


class TestNextMonth:
    def test_regular_month(self) -> None:
        dt = datetime(2024, 3, 15, tzinfo=UTC)
        result = _next_month(dt)
        assert result == datetime(2024, 4, 1, tzinfo=UTC)

    def test_december_wraps_to_january(self) -> None:
        dt = datetime(2024, 12, 5, tzinfo=UTC)
        result = _next_month(dt)
        assert result == datetime(2025, 1, 1, tzinfo=UTC)

    def test_result_has_zero_time(self) -> None:
        dt = datetime(2024, 6, 20, 15, 30, tzinfo=UTC)
        result = _next_month(dt)
        assert result.hour == 0
        assert result.minute == 0
        assert result.second == 0


class TestOHLCVDownloader:
    @pytest.fixture
    def downloader(self, tmp_path: Path, mock_exchange: AsyncMock) -> OHLCVDownloader:
        return OHLCVDownloader(exchange=mock_exchange, base_path=tmp_path / "raw")

    @pytest.mark.asyncio
    async def test_download_creates_parquet(
        self, downloader: OHLCVDownloader, mock_exchange: AsyncMock, tmp_path: Path
    ) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 10, tzinfo=UTC)
        mock_exchange.fetch_ohlcv.return_value = _make_raw_bars(start, 9)

        bars = await downloader.download(ExchangeId.BINANCE, "BTC/USDT", "1d", start, end)

        assert bars == 9
        parquet = tmp_path / "raw" / "binance" / "BTC_USDT" / "1d" / "2024-01.parquet"
        assert parquet.exists()

    @pytest.mark.asyncio
    async def test_download_returns_bar_count(
        self, downloader: OHLCVDownloader, mock_exchange: AsyncMock
    ) -> None:
        start = datetime(2024, 2, 1, tzinfo=UTC)
        end = datetime(2024, 2, 5, tzinfo=UTC)
        mock_exchange.fetch_ohlcv.return_value = _make_raw_bars(start, 4)

        bars = await downloader.download(ExchangeId.BINANCE, "BTC/USDT", "1d", start, end)

        assert bars == 4

    @pytest.mark.asyncio
    async def test_idempotent_deduplication(
        self, downloader: OHLCVDownloader, mock_exchange: AsyncMock, tmp_path: Path
    ) -> None:
        """Running with same data twice should not duplicate rows."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 5, tzinfo=UTC)
        raw = _make_raw_bars(start, 4)
        mock_exchange.fetch_ohlcv.return_value = raw

        await downloader.download(ExchangeId.BINANCE, "BTC/USDT", "1d", start, end)
        # Reset resume so it downloads again (simulate re-run)
        mock_exchange.fetch_ohlcv.return_value = raw
        parquet = tmp_path / "raw" / "binance" / "BTC_USDT" / "1d" / "2024-01.parquet"
        # Remove to force re-download without resume
        parquet.unlink()

        await downloader.download(ExchangeId.BINANCE, "BTC/USDT", "1d", start, end)

        df = pd.read_parquet(parquet)
        assert len(df) == 4  # no duplicates

    @pytest.mark.asyncio
    async def test_resumable_skips_completed_partition(
        self, downloader: OHLCVDownloader, mock_exchange: AsyncMock, tmp_path: Path
    ) -> None:
        """If last stored bar >= fetch_end, the partition is skipped on re-run."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 5, tzinfo=UTC)
        # 5 bars: last bar is at 2024-01-05 == end, so resume_from >= fetch_end → skip
        raw = _make_raw_bars(start, 5)
        mock_exchange.fetch_ohlcv.return_value = raw

        # First download — fetches and stores bars including the one at end
        await downloader.download(ExchangeId.BINANCE, "BTC/USDT", "1d", start, end)
        first_call_count = mock_exchange.fetch_ohlcv.call_count

        # Second download — resume sees last bar == end == fetch_end → skips fetch
        await downloader.download(ExchangeId.BINANCE, "BTC/USDT", "1d", start, end)

        assert mock_exchange.fetch_ohlcv.call_count == first_call_count

    @pytest.mark.asyncio
    async def test_lineage_file_written(
        self, downloader: OHLCVDownloader, mock_exchange: AsyncMock, tmp_path: Path
    ) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        mock_exchange.fetch_ohlcv.return_value = _make_raw_bars(start, 2)

        await downloader.download(ExchangeId.BINANCE, "BTC/USDT", "1d", start, end)

        lineage = tmp_path / "raw" / "binance" / "BTC_USDT" / "1d" / "2024-01.lineage.json"
        assert lineage.exists()
        import json

        data = json.loads(lineage.read_text())
        assert data["row_count"] == 2
        assert data["schema_version"] == "1.0"

    @pytest.mark.asyncio
    async def test_alpaca_lineage_uses_alpaca_source(
        self, downloader: OHLCVDownloader, mock_exchange: AsyncMock, tmp_path: Path
    ) -> None:
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 3, tzinfo=UTC)
        mock_exchange.fetch_ohlcv.return_value = _make_raw_bars(
            start,
            2,
            symbol="SPY",
            timeframe="1d",
        )

        await downloader.download(ExchangeId.ALPACA, "SPY", "1d", start, end)

        parquet = tmp_path / "raw" / "alpaca" / "SPY" / "1d" / "2024-01.parquet"
        df = pd.read_parquet(parquet)
        assert set(df["source"]) == {"alpaca.fetch_ohlcv"}

        import json

        lineage = json.loads(parquet.with_suffix(".lineage.json").read_text())
        assert lineage["source"] == "alpaca.fetch_ohlcv:SPY:1d"
        assert lineage["provider"] == "alpaca"
        assert lineage["exchange"] == "alpaca"

    @pytest.mark.asyncio
    async def test_empty_response_returns_zero(
        self, downloader: OHLCVDownloader, mock_exchange: AsyncMock
    ) -> None:
        mock_exchange.fetch_ohlcv.return_value = []
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 5, tzinfo=UTC)

        bars = await downloader.download(ExchangeId.BINANCE, "BTC/USDT", "1d", start, end)

        assert bars == 0

    @pytest.mark.asyncio
    async def test_data_path_from_settings(self, mock_exchange: AsyncMock, tmp_path: Path) -> None:
        """OHLCVDownloader with no explicit base_path uses settings.storage.raw_path."""
        with patch("trading_bot.data.ingestion.get_settings") as mock_settings:
            mock_settings.return_value.storage.raw_path = str(tmp_path / "configured")
            downloader = OHLCVDownloader(exchange=mock_exchange)
            assert downloader._base_path == tmp_path / "configured"

    @pytest.mark.asyncio
    async def test_exchange_ban_passes_through(
        self, downloader: OHLCVDownloader, mock_exchange: AsyncMock
    ) -> None:
        """ExchangeBannedError must NOT be wrapped in DataFetchError.

        Regression test for the Binance 418 cascade — daily_ohlcv_ingestion_job
        catches ExchangeBannedError specifically to emit a single deduped WARNING
        instead of a per-symbol ERROR.
        """
        from trading_bot.core.exceptions import ExchangeBannedError

        mock_exchange.fetch_ohlcv.side_effect = ExchangeBannedError(
            "Binance IP banned", banned_until_ms=1_779_808_947_147
        )
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 2, tzinfo=UTC)

        with pytest.raises(ExchangeBannedError) as exc_info:
            await downloader.download(ExchangeId.BINANCE, "BTC/USDT", "1d", start, end)

        assert exc_info.value.banned_until_ms == 1_779_808_947_147
