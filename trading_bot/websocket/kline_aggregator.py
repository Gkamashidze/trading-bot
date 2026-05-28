"""Persist closed Binance WebSocket kline events into OHLCV Parquet storage."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from trading_bot.core.models import ExchangeId
from trading_bot.data.ingestion import OHLCVDownloader
from trading_bot.observability.logging import get_logger
from trading_bot.observability.metrics import WEBSOCKET_KLINE_PERSISTED

log = get_logger(__name__)

_SOURCE = "binance.websocket_kline"


class BinanceKlineAggregator:
    """Consumes closed Binance kline WebSocket messages and persists OHLCV bars."""

    def __init__(
        self,
        symbols: list[str],
        timeframes: list[str],
        base_path: Path | None = None,
    ) -> None:
        self._symbols = symbols
        self._timeframes = timeframes
        self._symbol_by_stream = {_normalise_symbol(symbol): symbol for symbol in symbols}
        self._downloader = OHLCVDownloader(exchange=None, base_path=base_path)

    @property
    def streams(self) -> list[str]:
        """Return Binance combined-stream names for configured klines."""
        return [
            f"{_normalise_symbol(symbol).lower()}@kline_{timeframe}"
            for symbol in self._symbols
            for timeframe in self._timeframes
        ]

    async def handle_message(self, data: dict[str, Any]) -> None:
        """Persist a message if it is a closed kline event."""
        if data.get("e") != "kline":
            return
        kline = data.get("k")
        if not isinstance(kline, dict) or not kline.get("x"):
            return

        symbol_key = str(kline.get("s") or data.get("s") or "").upper()
        symbol = self._symbol_by_stream.get(symbol_key)
        if symbol is None:
            log.debug("ws_kline_skipped_unknown_symbol", symbol=symbol_key)
            return

        timeframe = str(kline["i"])
        bar = _bar_from_kline(kline)
        inserted = self._downloader.append_bars(
            exchange_id=ExchangeId.BINANCE,
            symbol=symbol,
            timeframe=timeframe,
            raw_bars=[bar],
            source=_SOURCE,
        )
        if inserted:
            WEBSOCKET_KLINE_PERSISTED.labels(
                exchange="binance",
                symbol=symbol,
                timeframe=timeframe,
            ).inc(inserted)
            log.info(
                "ws_kline_persisted",
                exchange="binance",
                symbol=symbol,
                timeframe=timeframe,
                open_time=bar["open_time"].isoformat(),
                inserted=inserted,
            )
        else:
            log.debug(
                "ws_kline_duplicate_skipped",
                exchange="binance",
                symbol=symbol,
                timeframe=timeframe,
                open_time=bar["open_time"].isoformat(),
            )


def _normalise_symbol(symbol: str) -> str:
    return symbol.split(":", 1)[0].replace("/", "").upper()


def _bar_from_kline(kline: dict[str, Any]) -> dict[str, Any]:
    return {
        "open_time": datetime.fromtimestamp(int(kline["t"]) / 1000, tz=UTC),
        "open": Decimal(str(kline["o"])),
        "high": Decimal(str(kline["h"])),
        "low": Decimal(str(kline["l"])),
        "close": Decimal(str(kline["c"])),
        "volume": Decimal(str(kline["v"])),
        "quote_volume": Decimal(str(kline.get("q", "0"))),
        "trade_count": int(kline["n"]) if kline.get("n") is not None else None,
        "close_time": datetime.fromtimestamp(int(kline["T"]) / 1000, tz=UTC),
    }
