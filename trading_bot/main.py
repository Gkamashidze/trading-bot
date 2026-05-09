"""Trading bot application entry point.

Startup sequence:
1. Load configuration (YAML + env vars)
2. Configure logging (structlog, JSON/console)
3. Configure tracing (OpenTelemetry)
4. Start health check HTTP server (port 8000) — Railway healthcheck
5. Start Prometheus metrics server
6. Init DB connection pool
7. Run Alembic migrations (safe — idempotent)
8. Init idempotency store + feature flag store
9. Register OS signal handlers (SIGTERM → graceful shutdown)
10. Register APScheduler jobs
11. Start scheduler
12. Log startup diagnostics
13. Wait for shutdown signal
14. Graceful shutdown (drain queues, close connections, exit 0)

Stage 0: no WebSocket, no strategies, no live trading.
Only data ingestion scheduler and health check are active.
"""

from __future__ import annotations

import asyncio
import sys

from aiohttp.web import AppRunner
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from trading_bot.alerts.telegram import TelegramAlerter
from trading_bot.config import get_settings
from trading_bot.database.connection import close_pool, init_pool
from trading_bot.feature_flags.store import FeatureFlagStore, set_default_store
from trading_bot.health import start_health_server, stop_health_server, update_health_state
from trading_bot.idempotency.decorator import set_default_store as set_idem_store
from trading_bot.idempotency.store import PostgresIdempotencyStore
from trading_bot.observability.logging import configure_logging, get_logger
from trading_bot.observability.metrics import start_metrics_server
from trading_bot.observability.tracing import configure_tracing
from trading_bot.scheduler.jobs import create_scheduler, register_default_jobs
from trading_bot.utils.signals import register_shutdown_handlers, wait_for_shutdown

log = get_logger(__name__)


async def _startup() -> tuple[AsyncIOScheduler | None, object, AppRunner, TelegramAlerter | None]:
    """Perform all startup tasks. Returns (scheduler, pool, health_runner, alerter)."""
    settings = get_settings()

    # ── Logging ──────────────────────────────────────────────────────────
    configure_logging(
        level=settings.logging.level,
        fmt=settings.logging.format,
        include_caller=settings.logging.include_caller,
    )

    # ── Tracing ──────────────────────────────────────────────────────────
    configure_tracing(
        service_name=settings.otel.service_name,
        exporter_type=settings.otel.exporter,
        otlp_endpoint=settings.otel.otlp_endpoint,
        order_sample_rate=settings.otel.order_sample_rate,
        data_fetch_sample_rate=settings.otel.data_fetch_sample_rate,
    )

    # ── Health Check Server ───────────────────────────────────────────────
    health_runner = await start_health_server(port=8000)
    update_health_state(environment=settings.environment, stage="0")

    # ── Prometheus ────────────────────────────────────────────────────────
    if settings.prometheus.enabled:
        start_metrics_server(port=settings.prometheus.port)
        log.info("prometheus_started", port=settings.prometheus.port)

    # ── Database ──────────────────────────────────────────────────────────
    if settings.database.url:
        pool = await init_pool(
            database_url=settings.database.url,
            min_size=settings.database.pool_min,
            max_size=settings.database.pool_max,
            command_timeout=float(settings.database.command_timeout),
        )
        update_health_state(db_connected=True)

        # Feature flags
        flag_store = FeatureFlagStore(pool)
        await flag_store.refresh()
        set_default_store(flag_store)

        # Idempotency store
        idem_store = PostgresIdempotencyStore(pool)
        set_idem_store(idem_store)
    else:
        pool = None
        log.warning(
            "database_not_configured",
            action="running_without_db",
            note="Feature flags and idempotency store unavailable",
        )

    # ── OS Signal Handlers ────────────────────────────────────────────────
    register_shutdown_handlers()

    # ── Scheduler ─────────────────────────────────────────────────────────
    scheduler = None
    if settings.database.url and pool is not None:
        scheduler = create_scheduler(database_url=settings.database.url)
        register_default_jobs(scheduler)
        scheduler.start()
        update_health_state(scheduler_running=True)
        log.info("scheduler_started")
    else:
        log.warning("scheduler_skipped", reason="DATABASE_URL not configured")

    # ── Telegram Alerter ─────────────────────────────────────────────────
    alerter = TelegramAlerter.from_env_optional()
    if alerter is None:
        log.warning(
            "telegram_not_configured",
            note="Set TELEGRAM_BOT_TOKEN + TELEGRAM_ALERT_CHAT_ID",
        )
    else:
        await alerter.send_startup(environment=settings.environment, stage="0")

    # ── Startup Diagnostics ───────────────────────────────────────────────
    log.info(
        "trading_bot_started",
        environment=settings.environment,
        config_version=settings.config_version,
        stage="0",
        live_trading="DISABLED",
        binance_testnet=settings.binance.testnet,
    )

    return scheduler, pool, health_runner, alerter


async def _shutdown(
    scheduler: AsyncIOScheduler | None,
    pool: object,
    health_runner: AppRunner | None,
    alerter: TelegramAlerter | None,
) -> None:
    """Graceful shutdown — drain, close, exit."""
    log.info("graceful_shutdown_initiated")

    if alerter is not None:
        await alerter.send_shutdown()

    if scheduler is not None:
        scheduler.shutdown(wait=True)
        log.info("scheduler_shutdown")

    if pool is not None:
        await close_pool()

    if health_runner is not None:
        await stop_health_server(health_runner)

    log.info("trading_bot_stopped")


async def main_async() -> None:
    scheduler = None
    pool = None
    health_runner = None
    alerter = None
    try:
        scheduler, pool, health_runner, alerter = await _startup()
        await wait_for_shutdown()
    except Exception as e:
        log.error("startup_failed", error=str(e), exc_info=True)
        sys.exit(1)
    finally:
        await _shutdown(scheduler, pool, health_runner, alerter)


def main() -> None:
    """Synchronous entry point (called by `trading-bot` CLI script)."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
