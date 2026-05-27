"""Scheduling safeguards for Binance ingestion jobs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from trading_bot.scheduler.jobs import create_scheduler, register_default_jobs


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
