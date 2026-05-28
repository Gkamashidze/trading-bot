"""Scheduling safeguards for Binance ingestion jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from trading_bot.scheduler.jobs import (
    _rest_gap_fill_required,
    create_scheduler,
    register_default_jobs,
)


def test_intraday_binance_jobs_are_staggered_on_startup() -> None:
    settings = SimpleNamespace(
        trading=SimpleNamespace(
            crypto=SimpleNamespace(
                exchange="binance",
                symbols=["BTC/USDT", "ETH/USDT"],
                timeframes=["1h"],
            ),
            equity=SimpleNamespace(exchange="alpaca", symbols=[], timeframes=["1d"]),
        ),
        market_context=SimpleNamespace(enabled=False),
        evidence=SimpleNamespace(enabled=False),
    )
    scheduler = create_scheduler(database_url="")

    with patch("trading_bot.config.get_settings", return_value=settings):
        register_default_jobs(scheduler)

    btc_job = scheduler.get_job("ohlcv_btc_usdt_1h")
    eth_job = scheduler.get_job("ohlcv_eth_usdt_1h")
    assert btc_job is not None
    assert eth_job is not None
    assert btc_job.next_run_time is not None
    assert eth_job.next_run_time is not None
    assert (eth_job.next_run_time - btc_job.next_run_time).total_seconds() >= 59


def _write_bar(tmp_path: Path, open_time: datetime) -> None:
    parquet = tmp_path / "raw" / "binance" / "BTC_USDT" / "1h" / "2026-05.parquet"
    parquet.parent.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "open_time": open_time,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            }
        ]
    ).to_parquet(parquet, index=False)


def test_gap_detection_skips_rest_when_websocket_data_is_fresh(tmp_path: Path) -> None:
    now = datetime(2026, 5, 28, 18, 0, tzinfo=UTC)
    _write_bar(tmp_path, now - timedelta(minutes=90))
    settings = SimpleNamespace(storage=SimpleNamespace(raw_path=str(tmp_path / "raw")))

    with patch("trading_bot.config.get_settings", return_value=settings):
        required, last_bar, age_s = _rest_gap_fill_required("binance", "BTC/USDT", "1h", now)

    assert required is False
    assert last_bar == now - timedelta(minutes=90)
    assert age_s == 5400


def test_gap_detection_triggers_rest_when_websocket_data_is_stale(tmp_path: Path) -> None:
    now = datetime(2026, 5, 28, 18, 0, tzinfo=UTC)
    _write_bar(tmp_path, now - timedelta(hours=3))
    settings = SimpleNamespace(storage=SimpleNamespace(raw_path=str(tmp_path / "raw")))

    with patch("trading_bot.config.get_settings", return_value=settings):
        required, last_bar, age_s = _rest_gap_fill_required("binance", "BTC/USDT", "1h", now)

    assert required is True
    assert last_bar == now - timedelta(hours=3)
    assert age_s == 10800


def test_gap_detection_triggers_bootstrap_when_no_parquet_exists(tmp_path: Path) -> None:
    now = datetime(2026, 5, 28, 18, 0, tzinfo=UTC)
    settings = SimpleNamespace(storage=SimpleNamespace(raw_path=str(tmp_path / "raw")))

    with patch("trading_bot.config.get_settings", return_value=settings):
        required, last_bar, age_s = _rest_gap_fill_required("binance", "BTC/USDT", "1h", now)

    assert required is True
    assert last_bar is None
    assert age_s is None
