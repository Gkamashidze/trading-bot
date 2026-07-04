"""Trading bot application entry point.

Startup sequence:
1. Load configuration (YAML + env vars)
2. Configure logging (structlog, JSON/console)
3. Configure tracing (OpenTelemetry)
4. Start FastAPI dashboard + /health server (uvicorn, port 8000)
5. Start Prometheus metrics server
6. Init DB connection pool
7. Init idempotency store + feature flag store
8. Register OS signal handlers (SIGTERM -> graceful shutdown)
9. Register APScheduler jobs
10. Start scheduler
11. Send Telegram startup alert
12. Log startup diagnostics
13. Wait for shutdown signal
14. Graceful shutdown (drain queues, close connections, exit 0)

Stage 0: no WebSocket, no strategies, no live trading.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from trading_bot.alerts.telegram import TelegramAlerter
from trading_bot.backtesting.runner import run_backtests
from trading_bot.config import get_settings
from trading_bot.dashboard.app import create_app, init_dashboard
from trading_bot.database.connection import close_pool, init_pool
from trading_bot.feature_flags.store import FeatureFlagStore, set_default_store
from trading_bot.idempotency.decorator import set_default_store as set_idem_store
from trading_bot.idempotency.store import PostgresIdempotencyStore
from trading_bot.market_context import refresh_market_context
from trading_bot.observability.logging import configure_logging, get_logger
from trading_bot.observability.metrics import start_metrics_server
from trading_bot.observability.tracing import configure_tracing
from trading_bot.oms.tracker import init_tracker
from trading_bot.scheduler.jobs import create_scheduler, register_default_jobs
from trading_bot.strategies.runner import refresh_signals
from trading_bot.utils.signals import register_shutdown_handlers, wait_for_shutdown
from trading_bot.websocket import BinanceWebSocketClient, get_price_cache

log = get_logger(__name__)


async def _run_dashboard() -> None:
    """Run uvicorn serving the FastAPI dashboard as a background task.

    Port is read from PORT env var (Railway injects this automatically).
    Falls back to 8000 for local development.
    """
    port = int(os.environ.get("PORT", "8000"))
    app = create_app()
    config = uvicorn.Config(
        app,
        host="0.0.0.0",  # noqa: S104
        port=port,
        log_level="warning",  # uvicorn logs go through structlog instead
        access_log=False,
    )
    server = uvicorn.Server(config)
    log.info("dashboard_started", port=port, path="/")
    await server.serve()


async def _startup() -> tuple[
    AsyncIOScheduler | None, object, TelegramAlerter | None, BinanceWebSocketClient | None
]:
    """Perform all startup tasks. Returns (scheduler, pool, alerter)."""
    settings = get_settings()

    # ── Logging ──────────────────────────────────────────────────────────
    configure_logging(
        level=settings.logging.level,
        fmt=settings.logging.format,
        include_caller=settings.logging.include_caller,
    )

    # Keep Binance ban/Retry-After state across Railway restarts. Otherwise a
    # deploy during an active ban immediately probes the banned IP again.
    from trading_bot.exchange.rate_limit import configure_state_store

    configure_state_store(Path(settings.storage.raw_path).parent / "exchange_circuit_state.json")

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

        # Risk state — Postgres-backed so drawdown/kill-switch state survives restarts
        from trading_bot.state.risk_state import PostgresRiskStateStore, set_risk_state_store

        _risk_store = PostgresRiskStateStore(pool)
        await _risk_store._ensure_row()
        set_risk_state_store(_risk_store)
        log.info("risk_state_store_initialized", backend="postgres")

        # OMS tracker — wire pool and rehydrate order history from DB
        tracker = init_tracker(pool)
        await tracker.load_recent()

        # Reconciler — OMS↔exchange consistency check (paper: vs PaperExchange).
        # Registered so the scheduled reconciliation job + router gate are live.
        from trading_bot.core.models import ExchangeId
        from trading_bot.execution.paper import PaperExchange
        from trading_bot.oms.reconciler import Reconciler, set_reconciler

        set_reconciler(Reconciler(exchange=PaperExchange(), exchange_id=ExchangeId.BINANCE))
        log.info("reconciler_initialized", exchange="binance", mode="paper")

        # ── Portfolio crash-recovery restore ─────────────────────────────────
        # 1. Load latest on-disk snapshot (hourly, /data/snapshots/).
        # 2. Replay any paper_orders fills that arrived after the snapshot.
        # This closes the gap for crashes between hourly snapshot writes.
        from trading_bot.portfolio.rebuilder import rebuild_portfolio
        from trading_bot.safety.circuit_breaker import get_circuit_breaker

        _snap, _fills = await rebuild_portfolio(pool)
        if _snap is not None:
            get_circuit_breaker().restore_state(
                tier=_snap.cb_tier,
                peak_tier=_snap.cb_peak_tier,
                tripped_at=_snap.cb_tripped_at,
            )
            log.info(
                "startup_restore_complete",
                snapshot_captured_at=_snap.captured_at,
                fills_replayed=_fills,
                cb_tier=_snap.cb_tier,
            )
        else:
            log.info("startup_restore_cold_start", fills_replayed=_fills)

        # Evidence store — start or resume paper testing session
        if settings.evidence.enabled:
            import os
            from decimal import Decimal as _Decimal

            from trading_bot.evidence import init_evidence_store, set_current_session_id
            from trading_bot.strategies.registry import get_strategy_registry

            ev_store = init_evidence_store(pool)
            try:
                strategies_list = [e.strategy_id for e in get_strategy_registry().all_entries()]
                ev_session = await ev_store.ensure_session(
                    environment=settings.environment,
                    config_snapshot=settings.snapshot(),
                    paper_capital=_Decimal(os.environ.get("PAPER_CAPITAL", "10000")),
                    symbols=settings.trading.crypto.symbols,
                    strategies=strategies_list,
                    git_commit=os.environ.get("GIT_COMMIT"),
                )
                set_current_session_id(ev_session.session_id)
                log.info(
                    "evidence_session_active",
                    session_id=str(ev_session.session_id),
                    status=ev_session.status,
                )

                # Backfill evidence from paper_orders (one-shot, idempotent).
                # Weeks of paper fills predate the evidence recorder — reconstruct
                # them so the Gate 0 report reflects real trading activity.
                from trading_bot.evidence.backfill import (
                    backfill_evidence_from_paper_orders,
                    needs_backfill,
                )

                if await needs_backfill(pool, ev_session.session_id):
                    _n = await backfill_evidence_from_paper_orders(
                        pool, ev_store, ev_session.session_id
                    )
                    log.info("evidence_backfill_ran", rows_inserted=_n)
            except Exception as ev_exc:
                log.warning("evidence_session_start_failed", error=str(ev_exc))
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
        log.info("scheduler_started")
    else:
        log.warning("scheduler_skipped", reason="DATABASE_URL not configured")

    # ── Strategy signals + backtests (initial computation, non-blocking) ───
    _signal_task = asyncio.create_task(refresh_signals(), name="initial_signal_refresh")
    del _signal_task  # fire-and-forget: task runs independently
    _bt_task = asyncio.create_task(run_backtests(), name="initial_backtest")
    del _bt_task  # fire-and-forget: task runs independently
    if settings.market_context.enabled:
        _mc_task = asyncio.create_task(
            refresh_market_context(), name="initial_market_context_refresh"
        )
        del _mc_task  # fire-and-forget: task runs independently
    log.info("signal_refresh_scheduled")

    # ── Telegram Operator Command Handler (Stage 7) ───────────────────────
    if pool is not None:
        from trading_bot.operator_console.telegram_commands import TelegramCommandHandler

        cmd_handler = TelegramCommandHandler.from_env_optional(pool=pool)
        if cmd_handler is not None:
            _cmd_task = asyncio.create_task(cmd_handler.run(), name="telegram_commands")
            del _cmd_task  # fire-and-forget: exits on shutdown via is_shutdown_requested()
            log.info("telegram_command_handler_started")
        else:
            log.info(
                "telegram_command_handler_skipped",
                reason="TELEGRAM_BOT_TOKEN or TELEGRAM_ALERT_CHAT_ID not set",
            )

    # ── WebSocket price feed + kline persistence ─────────────────────────
    from trading_bot.feature_flags import is_enabled

    ws_client = None
    ws_price_enabled = await is_enabled("websocket_enabled")
    ws_kline_enabled = await is_enabled("websocket_kline_ingestion_enabled") and await is_enabled(
        "data_ingestion_enabled"
    )
    if ws_price_enabled or ws_kline_enabled:
        price_cache = get_price_cache()
        ws_symbols = [s.replace("/", "") for s in settings.trading.crypto.symbols]
        price_symbols = ws_symbols if ws_price_enabled else []
        kline_aggregator = None
        kline_streams: list[str] = []
        if ws_kline_enabled:
            from trading_bot.websocket import BinanceKlineAggregator

            kline_aggregator = BinanceKlineAggregator(
                symbols=settings.trading.crypto.symbols,
                timeframes=settings.trading.crypto.timeframes,
            )
            kline_streams = kline_aggregator.streams
        ws_client = BinanceWebSocketClient(
            symbols=price_symbols,
            on_tick=price_cache.update,
            extra_streams=kline_streams,
            on_message=kline_aggregator.handle_message if kline_aggregator else None,
        )
        ws_client.start()
        log.info(
            "websocket_started",
            price_symbols=price_symbols,
            kline_streams=kline_streams,
        )
    else:
        log.info(
            "websocket_skipped_flag",
            flags=["websocket_enabled", "websocket_kline_ingestion_enabled"],
        )

    # ── Dashboard wiring (pool + scheduler available now) ─────────────────
    init_dashboard(pool=pool, scheduler=scheduler)

    # ── Telegram Alerter ─────────────────────────────────────────────────
    alerter = TelegramAlerter.from_env_optional()
    if alerter is None:
        log.warning(
            "telegram_not_configured",
            note="Set TELEGRAM_BOT_TOKEN + TELEGRAM_ALERT_CHAT_ID",
        )
    else:
        await alerter.send_startup(environment=settings.environment, stage="0")

    # ── DATA_PATH volume sanity check ─────────────────────────────────────
    _data_path = os.environ.get("DATA_PATH", "data/raw")
    if not _data_path.startswith("/data"):
        log.warning(
            "data_path_not_on_persistent_volume",
            data_path=_data_path,
            note="OHLCV and snapshots will be lost on redeploy — "
            "mount Railway Volume and set DATA_PATH=/data/raw",
        )

    # ── Startup Diagnostics ───────────────────────────────────────────────
    log.info(
        "trading_bot_started",
        environment=settings.environment,
        config_version=settings.config_version,
        stage="0",
        live_trading="DISABLED",
        binance_testnet=settings.binance.testnet,
        dashboard_url="http://0.0.0.0:8000",
    )

    return scheduler, pool, alerter, ws_client


async def _shutdown(
    scheduler: AsyncIOScheduler | None,
    pool: object,
    alerter: TelegramAlerter | None,
    ws_client: BinanceWebSocketClient | None = None,
) -> None:
    """Graceful shutdown — drain, close, exit."""
    log.info("graceful_shutdown_initiated")

    if ws_client is not None:
        ws_client.stop()

    if alerter is not None:
        await alerter.send_shutdown()

    if scheduler is not None:
        scheduler.shutdown(wait=True)
        log.info("scheduler_shutdown")

    if pool is not None:
        await close_pool()

    log.info("trading_bot_stopped")


async def main_async() -> None:
    # Start HTTP server IMMEDIATELY so Railway /health responds during startup.
    # uvicorn must be up before _startup() finishes to pass the 30s healthcheck.
    dashboard_task = asyncio.create_task(_run_dashboard())

    scheduler = None
    pool = None
    alerter = None
    ws_client = None
    try:
        scheduler, pool, alerter, ws_client = await _startup()
        await asyncio.gather(
            dashboard_task,
            wait_for_shutdown(),
            return_exceptions=True,
        )
    except Exception as e:
        log.error("startup_failed", error=str(e), exc_info=True)
        dashboard_task.cancel()
        sys.exit(1)
    finally:
        await _shutdown(scheduler, pool, alerter, ws_client)


def main() -> None:
    """Synchronous entry point (called by `trading-bot` CLI script)."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
