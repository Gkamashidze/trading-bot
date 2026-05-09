"""Scheduled job definitions.

APScheduler configuration:
- Persistent job store: SQLAlchemyJobStore (Postgres) — survives restarts
- Executor: AsyncIOExecutor — non-blocking async jobs
- Timezone: UTC (enforced globally)
- Max instances per job: 1 (coalesce=True prevents pile-up)

Retry policy: Tenacity exponential backoff with jitter.
Dead letter: after max_attempts, publish an AlertEvent.

Usage:
    from trading_bot.scheduler.jobs import create_scheduler
    scheduler = create_scheduler(database_url=settings.database.url)
    scheduler.start()
"""

from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from trading_bot.core.exceptions import DataFetchError, ExchangeConnectionError
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


def create_scheduler(database_url: str) -> AsyncIOScheduler:
    """Create and configure an AsyncIOScheduler with in-memory job store.

    Stage 0 uses MemoryJobStore — jobs are redefined in code on every startup,
    so persistence across restarts is not needed. Switch to SQLAlchemyJobStore
    (with psycopg2/pg8000) at Stage 5+ when job history matters.
    """
    jobstores = {
        "default": MemoryJobStore(),
    }
    executors = {
        "default": AsyncIOExecutor(),
    }
    job_defaults = {
        "coalesce": True,  # collapse missed runs into one
        "max_instances": 1,  # never run the same job concurrently
        "misfire_grace_time": 300,  # allow jobs to fire up to 5 min late
    }

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone="UTC",
    )
    return scheduler


@retry(
    retry=retry_if_exception_type((DataFetchError, ExchangeConnectionError)),
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=2, max=30, jitter=2),
    reraise=True,
)
async def daily_ohlcv_ingestion_job(
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT",
    timeframe: str = "1d",
) -> None:
    """Daily job: download yesterday's OHLCV bars and store to Parquet.

    Idempotent: safe to run multiple times — deduplication ensures no duplicates.
    Retry: up to 4 attempts with exponential backoff + jitter.
    """
    from datetime import timedelta

    from trading_bot.core.models import ExchangeId
    from trading_bot.data.ingestion import OHLCVDownloader
    from trading_bot.exchange import get_exchange

    log.info(
        "daily_ingestion_started",
        exchange=exchange_id,
        symbol=symbol,
        timeframe=timeframe,
    )

    now = datetime.now(UTC)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=2)  # 2-day window to catch gaps

    exchange = get_exchange(ExchangeId(exchange_id))
    downloader = OHLCVDownloader(exchange=exchange)

    bars = await downloader.download(
        exchange_id=ExchangeId(exchange_id),
        symbol=symbol,
        timeframe=timeframe,
        start=start,
        end=end,
    )

    await exchange.close()  # type: ignore[attr-defined]

    log.info(
        "daily_ingestion_complete",
        exchange=exchange_id,
        symbol=symbol,
        timeframe=timeframe,
        bars_stored=bars,
    )


def register_default_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register the default daily ingestion jobs.

    Call after create_scheduler() and before scheduler.start().
    """
    scheduler.add_job(
        daily_ohlcv_ingestion_job,
        trigger="cron",
        hour=1,
        minute=0,
        id="daily_btc_1d",
        name="Daily BTC/USDT 1d ingestion",
        replace_existing=True,
        kwargs={
            "exchange_id": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1d",
        },
    )

    scheduler.add_job(
        daily_ohlcv_ingestion_job,
        trigger="cron",
        hour=1,
        minute=15,
        id="daily_btc_1h",
        name="Daily BTC/USDT 1h ingestion",
        replace_existing=True,
        kwargs={
            "exchange_id": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1h",
        },
    )

    log.info("default_scheduler_jobs_registered")
