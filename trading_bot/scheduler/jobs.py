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

import inspect
from datetime import UTC, datetime
from typing import Any

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


_INTRADAY_TIMEFRAMES = {"1m", "5m", "15m", "30m", "1h"}
_TIMEFRAME_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600}

# Bootstrap window (calendar days) for each Wave 1 ETF on first ingestion run.
# Larger than required_history_days to provide richer backtest coverage.
_ETF_BOOTSTRAP_DAYS: dict[str, int] = {
    "SPY": 730,
    "QQQ": 730,
    "SOXX": 730,
    "IBIT": 365,  # launched Jan 2024; 365 days is the practical maximum
}


def _has_existing_data(exchange_id: str, symbol: str, timeframe: str) -> bool:
    """Return True if any Parquet file exists for this (exchange, symbol, timeframe)."""
    from pathlib import Path

    from trading_bot.config import get_settings

    symbol_safe = symbol.replace("/", "_").replace(":", "_")
    parquet_dir = Path(get_settings().storage.raw_path) / exchange_id / symbol_safe / timeframe
    return parquet_dir.exists() and any(parquet_dir.glob("*.parquet"))


async def _close_exchange_if_supported(exchange: Any) -> None:
    close = getattr(exchange, "close", None)
    if close is None:
        return
    result = close()
    if inspect.isawaitable(result):
        await result


async def _asset_data_ingestion_allowed(symbol: str) -> bool:
    """Honor global and per-asset feature flags before fetching data."""
    from trading_bot.asset_universe import get_asset_registry
    from trading_bot.feature_flags import is_enabled

    if not await is_enabled("data_ingestion_enabled"):
        log.info("ohlcv_ingestion_skipped_flag", symbol=symbol, flag="data_ingestion_enabled")
        return False

    registry = get_asset_registry()
    spec = registry.get(symbol)
    if spec is None:
        log.warning("ohlcv_ingestion_skipped_unknown_asset", symbol=symbol)
        return False
    if not registry.is_data_eligible(symbol):
        log.info("ohlcv_ingestion_skipped_disabled_asset", symbol=symbol)
        return False
    if spec.feature_flag and not await is_enabled(spec.feature_flag):
        log.info(
            "ohlcv_ingestion_skipped_asset_flag",
            symbol=symbol,
            feature_flag=spec.feature_flag,
        )
        return False
    return True


async def daily_ohlcv_ingestion_job(
    exchange_id: str = "binance",
    symbol: str = "BTC/USDT",
    timeframe: str = "1d",
    bootstrap_days: int = 730,
) -> None:
    """OHLCV ingestion job — window adapts to timeframe.

    Intraday (1h etc.):
      - Bootstrap (no existing data): 30 days of history so strategies have enough bars.
      - Gap-fill (data exists): end - 4 h window.
    Daily:
      - Bootstrap (no existing data): bootstrap_days of history (default 730).
      - Gap-fill (data exists): end - 3 days (covers weekend gaps).
    Idempotent: deduplication ensures no duplicates.
    Failures are alerted to Telegram so silent data outages are visible.
    """
    from datetime import timedelta

    from trading_bot.core.models import ExchangeId
    from trading_bot.data.ingestion import OHLCVDownloader
    from trading_bot.exchange import get_exchange

    log.info(
        "ohlcv_ingestion_started",
        exchange=exchange_id,
        symbol=symbol,
        timeframe=timeframe,
    )

    if not await _asset_data_ingestion_allowed(symbol):
        return

    now = datetime.now(UTC)
    if timeframe in _INTRADAY_TIMEFRAMES:
        interval_s = _TIMEFRAME_SECONDS[timeframe]
        ts = int(now.timestamp())
        end_ts = (ts // interval_s) * interval_s
        end = datetime.fromtimestamp(end_ts, tz=UTC)
        # Bootstrap: download 30 days on first run so strategies have enough bars.
        # Gap-fill: 4-hour window on subsequent runs (resume logic fills exact gap).
        bootstrap = not _has_existing_data(exchange_id, symbol, timeframe)
        start = end - timedelta(days=30 if bootstrap else 4)
    else:
        end = now.replace(hour=0, minute=0, second=0, microsecond=0)
        bootstrap = not _has_existing_data(exchange_id, symbol, timeframe)
        # Bootstrap: full history window; gap-fill: 3-day window (covers weekend gaps).
        start = end - timedelta(days=bootstrap_days if bootstrap else 3)

    exchange = get_exchange(ExchangeId(exchange_id))
    downloader = OHLCVDownloader(exchange=exchange)

    try:
        bars = await downloader.download(
            exchange_id=ExchangeId(exchange_id),
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
        )
    except Exception as e:
        log.error(
            "ohlcv_ingestion_failed",
            exchange=exchange_id,
            symbol=symbol,
            timeframe=timeframe,
            error=str(e),
        )
        _send_ingestion_alert(symbol, timeframe, str(e))
        raise
    finally:
        await _close_exchange_if_supported(exchange)

    log.info(
        "ohlcv_ingestion_complete",
        exchange=exchange_id,
        symbol=symbol,
        timeframe=timeframe,
        bars_stored=bars,
        bootstrap=bootstrap,
    )


def _send_ingestion_alert(symbol: str, timeframe: str, detail: str) -> None:
    """Fire a Telegram alert when OHLCV ingestion fails (non-blocking, best-effort)."""
    import asyncio

    from trading_bot.alerts.telegram import AlertLevel, TelegramAlerter

    alerter = TelegramAlerter.from_env_optional()
    if alerter is None:
        return

    async def _send() -> None:
        await alerter.send(
            AlertLevel.ERROR,
            f"Ingestion failed: {symbol} [{timeframe}]",
            detail=detail[:400],
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_send())  # noqa: RUF006
    except Exception:  # noqa: S110
        pass


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


_db_was_reachable: bool = True


async def db_health_monitor_job() -> None:
    """Ping DB every 30s — alert on loss and recovery. Used by Chaos Drill #1."""
    global _db_was_reachable
    from trading_bot.alerts.telegram import AlertLevel, TelegramAlerter
    from trading_bot.database.connection import get_pool

    try:
        pool = get_pool()
    except RuntimeError:
        return  # pool not yet initialised — skip

    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1", timeout=5.0)
        reachable = True
    except Exception as exc:
        reachable = False
        log.warning("database_unreachable", error=str(exc))

    if not reachable and _db_was_reachable:
        _db_was_reachable = False
        alerter = TelegramAlerter.from_env_optional()
        if alerter:
            await alerter.send(
                AlertLevel.WARNING,
                "database_unreachable",
                detail="Postgres ping failed — /readyz returning 503. Orders will be rejected.",
            )
    elif reachable and not _db_was_reachable:
        _db_was_reachable = True
        log.info("database_recovered")
        alerter = TelegramAlerter.from_env_optional()
        if alerter:
            await alerter.send(
                AlertLevel.SUCCESS,
                "database_recovered",
                detail="Postgres ping succeeded — /readyz returning 200. Pool reconnected.",
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


async def promotion_evaluation_job() -> None:
    """Evaluate promotion gates for all registered strategies. Runs daily.

    Results are logged only — no auto-promotion. Operator must confirm via Telegram.
    Requires the paper_orders table to exist (migration 0003).
    """
    from trading_bot.database.connection import get_pool
    from trading_bot.promotion.pipeline import evaluate_promotion_gates

    try:
        pool = get_pool()
    except RuntimeError:
        log.warning("promotion_evaluation_skipped", reason="no_db_pool")
        return
    await evaluate_promotion_gates(pool)
    log.info("promotion_evaluation_job_complete")


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


async def evidence_portfolio_snapshot_job() -> None:
    """Capture a portfolio snapshot into the evidence store. Runs every 15 min."""
    import hashlib
    from decimal import Decimal

    from trading_bot.evidence import get_current_session_id, get_evidence_store
    from trading_bot.evidence.models import PortfolioEvidenceSnapshot
    from trading_bot.portfolio.manager import get_portfolio_manager

    ev_store = get_evidence_store()
    session_id = get_current_session_id()
    if ev_store is None or session_id is None:
        log.debug("evidence_snapshot_skipped", reason="no_active_session")
        return

    portfolio = get_portfolio_manager()
    pf_snap = portfolio.get_snapshot()
    now = pf_snap.taken_at
    ts_bucket = now.strftime("%Y%m%d%H%M")
    raw = f"{session_id}|{ts_bucket}"
    idem_key = f"portfolio_snapshot:{hashlib.sha256(raw.encode()).hexdigest()[:16]}"

    positions_map = {pos.symbol: pos.quantity for pos in pf_snap.positions}
    snapshot = PortfolioEvidenceSnapshot(
        session_id=session_id,
        captured_at=now,
        total_equity=pf_snap.total_equity,
        cash_balance=pf_snap.cash_balance,
        positions={sym: Decimal(str(qty)) for sym, qty in positions_map.items()},
        unrealized_pnl=Decimal("0"),
        daily_pnl=pf_snap.daily_pnl,
        daily_drawdown_pct=pf_snap.daily_drawdown_pct,
        max_drawdown_pct=Decimal("0"),
        idempotency_key=idem_key,
    )
    inserted = await ev_store.insert_portfolio_snapshot(snapshot)
    log.debug("evidence_portfolio_snapshot_job_complete", inserted=inserted)


async def evidence_daily_summary_job() -> None:
    """Generate and persist the previous day's evidence summary. Runs at UTC 00:05."""
    from trading_bot.evidence import get_current_session_id, get_evidence_store
    from trading_bot.evidence.reporter import EvidenceReporter

    ev_store = get_evidence_store()
    session_id = get_current_session_id()
    if ev_store is None or session_id is None:
        log.debug("evidence_daily_summary_skipped", reason="no_active_session")
        return

    reporter = EvidenceReporter(ev_store)
    summary = await reporter.generate_and_persist_daily_summary(session_id)
    log.info("evidence_daily_summary_job_complete", summary_generated=summary is not None)


async def evidence_weekly_summary_job() -> None:
    """Generate and persist the previous week's evidence summary. Runs Monday 00:10 UTC."""
    from trading_bot.evidence import get_current_session_id, get_evidence_store
    from trading_bot.evidence.reporter import EvidenceReporter

    ev_store = get_evidence_store()
    session_id = get_current_session_id()
    if ev_store is None or session_id is None:
        log.debug("evidence_weekly_summary_skipped", reason="no_active_session")
        return

    reporter = EvidenceReporter(ev_store)
    summary = await reporter.generate_and_persist_weekly_summary(session_id)
    log.info("evidence_weekly_summary_job_complete", summary_generated=summary is not None)


def register_default_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register the default daily ingestion jobs.

    Symbols and timeframes are read from settings.trading.crypto and
    settings.trading.equity — edit base.yaml to add/remove assets without
    touching this file.

    Crypto jobs: Binance, hourly (intraday) or daily 01:00 UTC.
    Equity jobs: Alpaca, daily 01:30+ UTC (after crypto daily jobs).
    Bootstrap window for equity is derived from _ETF_BOOTSTRAP_DAYS.

    Call after create_scheduler() and before scheduler.start().
    """
    from trading_bot.config import get_settings

    settings = get_settings()
    crypto = settings.trading.crypto
    daily_minute_offset = 0
    for symbol in crypto.symbols:
        symbol_safe = symbol.replace("/", "_").replace(":", "_").lower()
        for timeframe in crypto.timeframes:
            job_id = f"ohlcv_{symbol_safe}_{timeframe}"
            kwargs = {
                "exchange_id": crypto.exchange,
                "symbol": symbol,
                "timeframe": timeframe,
            }
            if timeframe in _INTRADAY_TIMEFRAMES:
                scheduler.add_job(
                    daily_ohlcv_ingestion_job,
                    trigger="interval",
                    hours=1,
                    id=job_id,
                    name=f"Hourly {symbol} {timeframe} ingestion",
                    replace_existing=True,
                    next_run_time=datetime.now(UTC),  # fire immediately on startup
                    kwargs=kwargs,
                )
            else:
                scheduler.add_job(
                    daily_ohlcv_ingestion_job,
                    trigger="cron",
                    hour=1,
                    minute=daily_minute_offset,
                    id=job_id,
                    name=f"Daily {symbol} {timeframe} ingestion",
                    replace_existing=True,
                    kwargs=kwargs,
                )
                daily_minute_offset += 15

    # Equity (Alpaca) — daily bars only; start at minute 30 to avoid overlap with crypto
    equity = settings.trading.equity
    equity_minute_offset = 30
    for symbol in equity.symbols:
        symbol_safe = symbol.replace("/", "_").replace(":", "_").lower()
        bootstrap_days = _ETF_BOOTSTRAP_DAYS.get(symbol, 730)
        for timeframe in equity.timeframes:
            job_id = f"ohlcv_{symbol_safe}_{timeframe}"
            scheduler.add_job(
                daily_ohlcv_ingestion_job,
                trigger="cron",
                hour=1,
                minute=equity_minute_offset,
                id=job_id,
                name=f"Daily {symbol} {timeframe} ingestion (alpaca)",
                replace_existing=True,
                next_run_time=datetime.now(UTC),  # bootstrap immediately on startup
                kwargs={
                    "exchange_id": equity.exchange,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "bootstrap_days": bootstrap_days,
                },
            )
            equity_minute_offset += 5

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
        db_health_monitor_job,
        trigger="interval",
        seconds=30,
        id="db_health_monitor",
        name="DB connectivity ping + alert (30s)",
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

    scheduler.add_job(
        promotion_evaluation_job,
        trigger="cron",
        hour=2,
        minute=0,
        id="promotion_evaluation",
        name="Daily promotion gate evaluation (02:00 UTC)",
        replace_existing=True,
    )

    if settings.evidence.enabled:
        scheduler.add_job(
            evidence_portfolio_snapshot_job,
            trigger="interval",
            minutes=settings.evidence.portfolio_snapshot_interval_minutes,
            id="evidence_portfolio_snapshot",
            name="Evidence portfolio snapshot (15 min)",
            replace_existing=True,
        )

        scheduler.add_job(
            evidence_daily_summary_job,
            trigger="cron",
            hour=0,
            minute=5,
            id="evidence_daily_summary",
            name="Evidence daily summary (UTC 00:05)",
            replace_existing=True,
        )

        scheduler.add_job(
            evidence_weekly_summary_job,
            trigger="cron",
            day_of_week="mon",
            hour=0,
            minute=10,
            id="evidence_weekly_summary",
            name="Evidence weekly summary (Monday 00:10 UTC)",
            replace_existing=True,
        )

    log.info("default_scheduler_jobs_registered")
