"""Tests for WebSocket kline aggregation into Parquet."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from trading_bot.websocket.kline_aggregator import BinanceKlineAggregator


def _kline_payload(closed: bool = True, open_ms: int = 1_705_320_000_000) -> dict:
    return {
        "e": "kline",
        "E": open_ms + 3_600_000,
        "s": "BTCUSDT",
        "k": {
            "t": open_ms,
            "T": open_ms + 3_599_999,
            "s": "BTCUSDT",
            "i": "1h",
            "o": "50000.0",
            "c": "50100.0",
            "h": "50200.0",
            "l": "49900.0",
            "v": "12.5",
            "n": 123,
            "x": closed,
            "q": "626250.0",
        },
    }


@pytest.mark.asyncio
async def test_closed_kline_appends_to_parquet_once(tmp_path: Path) -> None:
    aggregator = BinanceKlineAggregator(["BTC/USDT"], ["1h"], base_path=tmp_path / "raw")
    payload = _kline_payload()

    await aggregator.handle_message(payload)
    await aggregator.handle_message(payload)

    parquet = tmp_path / "raw" / "binance" / "BTC_USDT" / "1h" / "2024-01.parquet"
    df = pd.read_parquet(parquet)
    assert len(df) == 1
    assert df.iloc[0]["open_time"] == datetime(2024, 1, 15, 12, 0, tzinfo=UTC)
    assert set(df["source"]) == {"binance.websocket_kline"}


@pytest.mark.asyncio
async def test_open_kline_does_not_append(tmp_path: Path) -> None:
    aggregator = BinanceKlineAggregator(["BTC/USDT"], ["1h"], base_path=tmp_path / "raw")

    await aggregator.handle_message(_kline_payload(closed=False))

    parquet = tmp_path / "raw" / "binance" / "BTC_USDT" / "1h" / "2024-01.parquet"
    assert not parquet.exists()


@pytest.mark.asyncio
async def test_closed_bars_are_written_before_disconnect(tmp_path: Path) -> None:
    aggregator = BinanceKlineAggregator(["BTC/USDT"], ["1h"], base_path=tmp_path / "raw")

    await aggregator.handle_message(_kline_payload(open_ms=1_705_320_000_000))
    await aggregator.handle_message(_kline_payload(open_ms=1_705_323_600_000))

    parquet = tmp_path / "raw" / "binance" / "BTC_USDT" / "1h" / "2024-01.parquet"
    df = pd.read_parquet(parquet)
    assert len(df) == 2
    assert list(pd.to_datetime(df["open_time"], utc=True)) == [
        pd.Timestamp("2024-01-15T12:00:00Z"),
        pd.Timestamp("2024-01-15T13:00:00Z"),
    ]
