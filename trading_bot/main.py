"""Trading bot application entry point.

Startup sequence:
1. Load configuration (YAML + env vars)
2. Configure logging (structlog, JSON/console)
3. Configure tracing (OpenTelemetry)
4. Start Prometheus metrics server
5. Init DB connection pool
6. Run Alembic migrations (safe — idempotent)
7. Init idempotency store + feature flag store
8. Register OS signal handlers (SIGTERM → graceful shutdown)
9. Register APScheduler jobs
10. Start scheduler
11. Log startup diagnostics
12. Wait for shutdown signal
13. Graceful shutdown (drain queues, close connections, exit 0)

Stage 0: no WebSocket, no strategies, no live trading.
Only data ingestion scheduler and health check are active.
"""

from __future__ import annotations

import asyncio
import sys

from trading_bot.config import get_settings
from trading_bot.database.connection import close_pool, get_pool, init_pool
from trading_bot.feature_flags.store import FeatureFlagStore, set_default_store
from trading_bot.idempotency.decorator import set_default_store as set_idem_store
from trading_bot.idempotency.store import PostgresIdempotencyStore
from trading_bot.observability.logging import configure_logging, get_logger
from trading_bot.observability.metrics import start_metrics_server
from trading_bot.observability.tracing import configure_tracing
from trading_bot.scheduler.jobs import create_scheduler, register_default_jobs
from trading_bot.utils.signals import register_shutdown_handlers, wait_for_shutdown

log = get_logger(__name__)


async def _startup() -> tuple[object, object]:
    """Perform all startup tasks. Returns (scheduler, pool)."""
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

        # Feature flags
        flag_store = FeatureFlagStore(pool)
        await flag_store.refresh()
        set_default_store(flag_store)

        # Idempotency store
        idem_store = PostgresIdempotencyStore(pool)
        set_idem_store(idem_store)
    else:
        pool = None  # type: ignore[assignment]
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
        log.info("scheduler_started")
    else:
        log.warning("scheduler_skipped", reason="DATABASE_URL not configured")

    # ── Startup Diagnostics ───────────────────────────────────────────────
    log.info(
        "trading_bot_started",
        environment=settings.environment,
        config_version=settings.config_version,
        stage="0",
        live_trading="DISABLED",
        binance_testnet=settings.binance.testnet,
    )

    return scheduler, pool


async def _shutdown(scheduler: object, pool: object) -> None:
    """Graceful shutdown — drain, close, exit."""
    log.info("graceful_shutdown_initiated")

    if scheduler is not None:
        scheduler.shutdown(wait=True)  # type: ignore[union-attr]
        log.info("scheduler_shutdown")

    if pool is not None:
        await close_pool()

    log.info("trading_bot_stopped")


async def main_async() -> None:
    scheduler = None
    pool = None
    try:
        scheduler, pool = await _startup()
        await wait_for_shutdown()
    except Exception as e:
        log.error("startup_failed", error=str(e), exc_info=True)
        sys.exit(1)
    finally:
        await _shutdown(scheduler, pool)


def main() -> None:
    """Synchronous entry point (called by `trading-bot` CLI script)."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
