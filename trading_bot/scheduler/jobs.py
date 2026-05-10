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
async def signal_refresh_job() -> None:
    """Recompute all strategy signals from latest Parquet data.

    Runs every 15 minutes. Safe to miss a run (coalesce=True).
    """
    from trading_bot.strategies.runner import refresh_signals

    results = await refresh_signals()
    log.info("signal_refresh_job_complete", signals_computed=len(results))


async def backtest_refresh_job() -> None:
    """Re-run backtests against latest Parquet data.

    Runs every 6 hours. Fast (<1s for 500 daily bars).
    """
    from trading_bot.backtesting.runner import run_backtests

    results = await run_backtests()
    log.info("backtest_refresh_job_complete", strategies=len(results))


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


async def market_context_refresh_job() -> None:
    """Fetch Fear & Greed, Funding Rate, and FRED macro data.

    Runs every hour. Each provider has its own TTL cache, so the actual
    HTTP request only fires when the cache has expired.
    """
    from trading_bot.market_context import refresh_market_context

    ctx = await refresh_market_context()
    log.info(
        "market_context_job_complete",
        fear_greed=ctx.fear_greed_value,
        funding_rate=ctx.funding_rate,
        fed_rate=ctx.fed_funds_rate,
        cpi_yoy=ctx.cpi_yoy,
    )


async def circuit_breaker_monitor_job() -> None:
    """Check drawdown vs circuit breaker thresholds. Runs every 5 minutes."""
    from trading_bot.safety.circuit_breaker import get_circuit_breaker

    cb = get_circuit_breaker()
    tier = await cb.check()
    log.info("circuit_breaker_monitor_job_complete", tier=tier, drawdown_pct=cb.last_drawdown_pct)


async def daily_portfolio_reset_job() -> None:
    """Reset portfolio day-start equity and circuit breaker state. Runs at UTC midnight."""
    from trading_bot.portfolio.manager import get_portfolio_manager
    from trading_bot.safety.circuit_breaker import get_circuit_breaker

    portfolio = get_portfolio_manager()
    portfolio.reset_day()

    cb = get_circuit_breaker()
    cb.reset_day()

    log.info("daily_portfolio_reset_job_complete")


async def state_snapshot_job() -> None:
    """Capture and persist portfolio + circuit breaker state. Runs every hour.

    Writes JSON snapshot to /data/snapshots/ for disaster recovery.
    Prunes files older than 7 days (168 hourly snapshots).
    """
    from trading_bot.disaster_recovery.snapshotter import (
        capture_snapshot,
        prune_old_snapshots,
        save_snapshot,
    )

    snapshot = capture_snapshot()
    save_snapshot(snapshot)
    prune_old_snapshots()
    log.info(
        "state_snapshot_job_complete",
        equity=snapshot.total_equity,
        cb_tier=snapshot.cb_tier,
    )


def register_default_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register the default daily ingestion jobs.

    Symbols and timeframes are read from settings.trading.crypto — edit
    base.yaml (or an env-specific YAML) to add/remove assets without
    touching this file.

    Call after create_scheduler() and before scheduler.start().
    """
    from trading_bot.config import get_settings

    crypto = get_settings().trading.crypto
    minute_offset = 0
    for symbol in crypto.symbols:
        symbol_safe = symbol.replace("/", "_").replace(":", "_").lower()
        for timeframe in crypto.timeframes:
            job_id = f"daily_{symbol_safe}_{timeframe}"
            scheduler.add_job(
                daily_ohlcv_ingestion_job,
                trigger="cron",
                hour=1,
                minute=minute_offset,
                id=job_id,
                name=f"Daily {symbol} {timeframe} ingestion",
                replace_existing=True,
                kwargs={
                    "exchange_id": crypto.exchange,
                    "symbol": symbol,
                    "timeframe": timeframe,
                },
            )
            minute_offset += 15

    scheduler.add_job(
        signal_refresh_job,
        trigger="interval",
        minutes=15,
        id="signal_refresh",
        name="Strategy signal refresh (15 min)",
        replace_existing=True,
    )

    scheduler.add_job(
        backtest_refresh_job,
        trigger="interval",
        hours=6,
        id="backtest_refresh",
        name="Backtest refresh (6h)",
        replace_existing=True,
    )

    settings = get_settings()
    if settings.market_context.enabled:
        scheduler.add_job(
            market_context_refresh_job,
            trigger="interval",
            minutes=settings.market_context.refresh_interval_minutes,
            id="market_context_refresh",
            name="Market context refresh (Fear&Greed, Funding Rate, Macro)",
            replace_existing=True,
        )

    scheduler.add_job(
        circuit_breaker_monitor_job,
        trigger="interval",
        minutes=5,
        id="circuit_breaker_monitor",
        name="Circuit breaker drawdown monitor (5 min)",
        replace_existing=True,
    )

    scheduler.add_job(
        daily_portfolio_reset_job,
        trigger="cron",
        hour=0,
        minute=0,
        id="daily_portfolio_reset",
        name="Daily portfolio + circuit breaker reset (UTC midnight)",
        replace_existing=True,
    )

    scheduler.add_job(
        state_snapshot_job,
        trigger="interval",
        minutes=60,
        id="state_snapshot",
        name="Hourly portfolio state snapshot (disaster recovery)",
        replace_existing=True,
    )

    log.info("default_scheduler_jobs_registered")
