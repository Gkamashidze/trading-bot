"""Historical OHLCV data downloader — idempotent, partitioned, resumable.

Storage layout (write-once, immutable):
    data/raw/{exchange}/{symbol_safe}/{timeframe}/{YYYY-MM}.parquet

Partitioning by (exchange, symbol, timeframe, month):
- Enables efficient range scans in DuckDB
- Supports incremental downloads (resume from last fetched timestamp)
- Prevents full re-download on re-run (idempotent)

Idempotency:
- Before downloading a period, check if the Parquet file already exists
- Resume from the last timestamp in the existing file
- Deduplication after merge: keep the latest version of each open_time

Data lineage:
- Each file has a companion _lineage.json with source/fetched_at/schema_version
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from trading_bot.config import get_settings
from trading_bot.core.exceptions import DataFetchError
from trading_bot.core.models import DataLineage, ExchangeId
from trading_bot.observability.logging import get_logger
from trading_bot.observability.tracing import start_span

log = get_logger(__name__)

_SCHEMA_VERSION = "1.0"


def _default_raw_base() -> Path:
    """Return configured data path (DATA_PATH env var) or development fallback."""
    return Path(get_settings().storage.raw_path)


class OHLCVDownloader:
    """Downloads and stores historical OHLCV data in partitioned Parquet.

    Resumable: checks existing files and starts from the last stored timestamp.
    Idempotent: re-running with the same parameters produces the same output.
    """

    def __init__(
        self,
        exchange: Any,
        base_path: Path | None = None,
        batch_size: int = 1000,
    ) -> None:
        self._exchange = exchange
        self._base_path = base_path if base_path is not None else _default_raw_base()
        self._batch_size = batch_size

    def _partition_path(
        self,
        exchange_id: str,
        symbol: str,
        timeframe: str,
        year: int,
        month: int,
    ) -> Path:
        """Return Parquet file path for a given (exchange, symbol, timeframe, month)."""
        symbol_safe = symbol.replace("/", "_").replace(":", "_")
        return (
            self._base_path
            / exchange_id
            / symbol_safe
            / timeframe
            / f"{year:04d}-{month:02d}.parquet"
        )

    def _lineage_path(self, parquet_path: Path) -> Path:
        return parquet_path.with_suffix(".lineage.json")

    def _get_resume_timestamp(self, parquet_path: Path) -> datetime | None:
        """If the file exists, return the last timestamp for resumable download."""
        if not parquet_path.exists():
            return None
        try:
            df = pd.read_parquet(parquet_path, columns=["open_time"])
            if df.empty:
                return None
            last_ts = pd.to_datetime(df["open_time"].max(), utc=True).to_pydatetime()
            log.debug(
                "resume_from_checkpoint",
                path=str(parquet_path),
                last_timestamp=last_ts.isoformat(),
            )
            return cast(datetime, last_ts)
        except Exception as e:
            log.warning("resume_timestamp_read_failed", path=str(parquet_path), error=str(e))
            return None

    async def download(
        self,
        exchange_id: ExchangeId,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """Download OHLCV bars and store as partitioned Parquet.

        Returns total number of bars stored.
        """
        total_bars = 0
        current = start

        with start_span(
            "ingestion.download",
            {
                "exchange": str(exchange_id),
                "symbol": symbol,
                "timeframe": timeframe,
            },
        ):
            while current < end:
                # Work month-by-month for partition alignment
                month_end = _next_month(current)
                fetch_end = min(month_end, end)

                parquet_path = self._partition_path(
                    str(exchange_id),
                    symbol,
                    timeframe,
                    current.year,
                    current.month,
                )

                # Resumable: start from last stored timestamp
                resume_from = self._get_resume_timestamp(parquet_path)
                fetch_start = resume_from or current

                if fetch_start >= fetch_end:
                    log.debug(
                        "partition_already_complete",
                        path=str(parquet_path),
                    )
                    current = month_end
                    continue

                bars = await self._fetch_and_store(
                    exchange_id=exchange_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=fetch_start,
                    end=fetch_end,
                    parquet_path=parquet_path,
                )
                total_bars += bars
                current = month_end

        log.info(
            "download_complete",
            exchange=str(exchange_id),
            symbol=symbol,
            timeframe=timeframe,
            total_bars=total_bars,
        )
        return total_bars

    async def _fetch_and_store(
        self,
        exchange_id: ExchangeId,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        parquet_path: Path,
    ) -> int:
        """Fetch a chunk, validate, merge with existing file, save."""
        fetched_at = datetime.now(UTC)

        try:
            raw_bars: list[dict[str, Any]] = await self._exchange.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                since=start,
                limit=self._batch_size,
            )
        except Exception as e:
            raise DataFetchError(
                f"Failed to fetch OHLCV for {symbol} [{timeframe}] from {start}: {e}"
            ) from e

        if not raw_bars:
            log.debug("no_bars_returned", symbol=symbol, start=start.isoformat())
            return 0

        # Convert to DataFrame
        df = pd.DataFrame(raw_bars)
        df["symbol"] = symbol
        df["exchange"] = str(exchange_id)
        df["timeframe"] = timeframe
        df["source"] = "binance.fetch_ohlcv"
        df["schema_version"] = _SCHEMA_VERSION
        df["fetched_at"] = fetched_at

        # Filter to requested time range
        df = df[df["open_time"] <= end]

        if df.empty:
            return 0

        # Merge with existing file (idempotent: deduplicate on open_time)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        if parquet_path.exists():  # noqa: ASYNC240
            existing = pd.read_parquet(parquet_path)
            df = pd.concat([existing, df], ignore_index=True)

        df = df.drop_duplicates(subset=["open_time"], keep="last")
        df = df.sort_values("open_time").reset_index(drop=True)

        # Write Parquet
        df.to_parquet(parquet_path, index=False, compression="snappy")

        # Write lineage
        lineage = DataLineage(
            source=f"binance.fetch_ohlcv:{symbol}:{timeframe}",
            fetched_at=fetched_at,
            row_count=len(df),
            schema_version=_SCHEMA_VERSION,
        )
        self._lineage_path(parquet_path).write_text(
            json.dumps(lineage.model_dump(mode="json"), indent=2, default=str)
        )

        log.info(
            "partition_written",
            path=str(parquet_path),
            rows=len(df),
            symbol=symbol,
        )
        return len(df)


def _next_month(dt: datetime) -> datetime:
    """Return the first day of the month following dt."""
    if dt.month == 12:
        return dt.replace(
            year=dt.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
    return dt.replace(month=dt.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
