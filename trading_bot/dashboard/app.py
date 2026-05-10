"""FastAPI dashboard application.

Routes:
    GET /                         - Main dashboard page (full HTML)
    GET /partials/status          - htmx partial: system status card
    GET /partials/flags           - htmx partial: feature flags card
    GET /partials/jobs            - htmx partial: scheduler jobs card
    GET /partials/audit           - htmx partial: recent audit log entries
    GET /health                   - JSON health check (Railway healthcheck)
    POST /flags/{name}/toggle     - Toggle a feature flag on/off
    POST /admin/backfill          - Trigger historical OHLCV download (background task)
    GET  /admin/backfill/status   - JSON status of running backfill
    GET  /partials/paper_portfolio  - htmx partial: paper trading portfolio card
    GET  /partials/safety          - htmx partial: safety layer (kill switch + circuit breaker)
    GET  /partials/market_context  - htmx partial: market context (Fear&Greed, Funding, Macro)
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from trading_bot.backtesting.runner import get_last_backtest_at, get_latest_backtest
from trading_bot.observability.logging import get_logger
from trading_bot.oms.tracker import get_order_tracker
from trading_bot.portfolio.manager import get_portfolio_manager
from trading_bot.strategies.runner import get_last_computed_at, get_latest_signals
from trading_bot.websocket.price_cache import get_price_cache

log = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Set by init_dashboard() after DB + scheduler are ready
_pool: Any = None
_scheduler: Any = None
_start_time = time.time()

# Backfill state — tracks running/completed download jobs
_backfill_task: asyncio.Task[None] | None = None
_backfill_status: dict[str, Any] = {
    "running": False,
    "symbol": None,
    "timeframe": None,
    "started_at": None,
    "finished_at": None,
    "bars_stored": None,
    "error": None,
}


def init_dashboard(pool: Any, scheduler: Any) -> None:
    """Wire up DB pool and scheduler references after startup."""
    global _pool, _scheduler
    _pool = pool
    _scheduler = scheduler


def create_app() -> FastAPI:
    app = FastAPI(title="Trading Bot Dashboard", docs_url=None, redoc_url=None)

    @app.get("/health", response_class=JSONResponse)
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "uptime_seconds": int(time.time() - _start_time),
            "db_connected": _pool is not None,
            "scheduler_running": _scheduler is not None and _scheduler.running,
            "stage": "8",
            "live_trading_enabled": False,
        }

    @app.get("/healthz", response_class=JSONResponse)
    async def healthz() -> JSONResponse:
        """Kubernetes/Railway liveness probe — is the process alive?

        Always returns 200 as long as the process can handle requests.
        Does NOT check DB or scheduler state (that would cause restart loops
        during DB maintenance windows).
        """
        return JSONResponse({"status": "alive", "uptime_seconds": int(time.time() - _start_time)})

    @app.get("/readyz", response_class=JSONResponse)
    async def readyz() -> JSONResponse:
        """Railway readiness probe — is the bot ready to serve traffic?

        Returns 200 when DB is connected and scheduler is running.
        Returns 503 during startup or if a critical dependency is unavailable.
        Railway waits for 200 before routing traffic to this instance.
        """
        db_ok = _pool is not None
        sched_ok = _scheduler is not None and _scheduler.running
        ready = db_ok and sched_ok
        body = {
            "status": "ready" if ready else "not_ready",
            "db_connected": db_ok,
            "scheduler_running": sched_ok,
        }
        status_code = 200 if ready else 503
        return JSONResponse(body, status_code=status_code)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request=request, name="index.html")

    @app.get("/partials/status", response_class=HTMLResponse)
    async def partial_status(request: Request) -> HTMLResponse:
        uptime = int(time.time() - _start_time)
        hours, remainder = divmod(uptime, 3600)
        minutes, seconds = divmod(remainder, 60)
        return templates.TemplateResponse(
            request=request,
            name="partials/status.html",
            context={
                "db_connected": _pool is not None,
                "scheduler_running": _scheduler is not None and _scheduler.running,
                "uptime": f"{hours:02d}:{minutes:02d}:{seconds:02d}",
                "stage": "8",
            },
        )

    @app.get("/partials/flags", response_class=HTMLResponse)
    async def partial_flags(request: Request) -> HTMLResponse:
        flags: list[dict[str, Any]] = []
        if _pool is not None:
            try:
                async with _pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT flag_name AS name, enabled, reason AS description"
                        " FROM feature_flags ORDER BY flag_name"
                    )
                    flags = [dict(r) for r in rows]
            except Exception as e:
                log.warning("dashboard_flags_fetch_failed", error=str(e))
        return templates.TemplateResponse(
            request=request,
            name="partials/flags.html",
            context={"flags": flags, "pool_missing": _pool is None},
        )

    @app.get("/partials/jobs", response_class=HTMLResponse)
    async def partial_jobs(request: Request) -> HTMLResponse:
        jobs: list[dict[str, Any]] = []
        if _scheduler is not None:
            for job in _scheduler.get_jobs():
                next_run = job.next_run_time
                jobs.append(
                    {
                        "id": job.id,
                        "name": job.name,
                        "next_run": next_run.strftime("%Y-%m-%d %H:%M UTC") if next_run else "—",
                        "trigger": str(job.trigger),
                    }
                )
        return templates.TemplateResponse(
            request=request,
            name="partials/jobs.html",
            context={"jobs": jobs, "scheduler_off": _scheduler is None},
        )

    @app.get("/partials/audit", response_class=HTMLResponse)
    async def partial_audit(request: Request) -> HTMLResponse:
        entries: list[dict[str, Any]] = []
        if _pool is not None:
            try:
                async with _pool.acquire() as conn:
                    rows = await conn.fetch(
                        """SELECT event_type, actor,
                                  payload::text AS details,
                                  occurred_at AS created_at
                           FROM audit_log
                           ORDER BY occurred_at DESC
                           LIMIT 30"""
                    )
                    entries = [dict(r) for r in rows]
            except Exception as e:
                log.warning("dashboard_audit_fetch_failed", error=str(e))
        return templates.TemplateResponse(
            request=request,
            name="partials/audit.html",
            context={"entries": entries},
        )

    @app.post("/flags/{name}/toggle", response_class=HTMLResponse)
    async def toggle_flag(name: str, request: Request) -> HTMLResponse:
        if _pool is None:
            return HTMLResponse("<p class='text-red-500'>DB not connected</p>", status_code=503)
        try:
            async with _pool.acquire() as conn:
                row = await conn.fetchrow(
                    """UPDATE feature_flags
                       SET enabled = NOT enabled, changed_at = NOW()
                       WHERE flag_name = $1
                       RETURNING flag_name AS name, enabled, reason AS description""",
                    name,
                )
            if row is None:
                return HTMLResponse("<p class='text-red-500'>Flag not found</p>", status_code=404)
            log.info("feature_flag_toggled", flag=name, enabled=row["enabled"])
            flags = [dict(row)]
        except Exception as e:
            log.error("flag_toggle_failed", flag=name, error=str(e))
            return HTMLResponse(f"<p class='text-red-500'>Error: {e}</p>", status_code=500)

        return templates.TemplateResponse(
            request=request,
            name="partials/flags.html",
            context={"flags": flags, "pool_missing": False},
        )

    @app.get("/partials/backfill", response_class=HTMLResponse)
    async def partial_backfill_status(request: Request) -> HTMLResponse:
        """Show data availability summary + backfill trigger button."""
        from pathlib import Path

        from trading_bot.config import get_settings

        raw_path = Path(get_settings().storage.raw_path)
        parquet_dir = raw_path / "binance" / "BTC_USDT" / "1d"

        bar_count = 0
        date_from: str | None = None
        date_to: str | None = None

        if parquet_dir.exists():
            import pandas as pd

            files = sorted(parquet_dir.glob("*.parquet"))
            if files:
                frames = []
                for f in files:
                    try:
                        frames.append(pd.read_parquet(f, columns=["open_time"]))
                    except Exception as e:
                        log.warning("backfill_parquet_read_error", file=str(f), error=str(e))
                if frames:
                    combined = pd.concat(frames).drop_duplicates()
                    bar_count = len(combined)
                    ts = combined["open_time"].sort_values()
                    date_from = str(ts.iloc[0])[:10]
                    date_to = str(ts.iloc[-1])[:10]

        return templates.TemplateResponse(
            request=request,
            name="partials/backfill.html",
            context={
                "bar_count": bar_count,
                "date_from": date_from,
                "date_to": date_to,
                "backfill": _backfill_status,
            },
        )

    @app.post("/admin/backfill", response_class=JSONResponse)
    async def trigger_backfill(request: Request) -> JSONResponse:
        """Start a historical OHLCV backfill as a background task.

        Query params: symbol (default BTC/USDT), timeframe (default 1d),
        days_back (default 730 = 2 years).
        """
        global _backfill_status

        if _backfill_status["running"]:
            return JSONResponse(
                {"error": "backfill already running", **_backfill_status}, status_code=409
            )

        params = dict(request.query_params)
        symbol = params.get("symbol", "BTC/USDT")
        timeframe = params.get("timeframe", "1d")
        days_back = int(params.get("days_back", 730))

        async def _run_backfill() -> None:
            global _backfill_status
            import datetime as dt

            from trading_bot.core.models import ExchangeId
            from trading_bot.data.ingestion import OHLCVDownloader
            from trading_bot.exchange import get_exchange

            _backfill_status = {
                "running": True,
                "symbol": symbol,
                "timeframe": timeframe,
                "started_at": datetime.now(UTC).isoformat(),
                "finished_at": None,
                "bars_stored": None,
                "error": None,
            }
            try:
                end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
                start = end - dt.timedelta(days=days_back)
                exchange = get_exchange(ExchangeId.BINANCE)
                downloader = OHLCVDownloader(exchange=exchange)
                bars = await downloader.download(
                    exchange_id=ExchangeId.BINANCE,
                    symbol=symbol,
                    timeframe=timeframe,
                    start=start,
                    end=end,
                )
                await exchange.close()  # type: ignore[attr-defined]
                _backfill_status["running"] = False
                _backfill_status["finished_at"] = datetime.now(UTC).isoformat()
                _backfill_status["bars_stored"] = bars
                log.info("backfill_complete", symbol=symbol, timeframe=timeframe, bars=bars)
            except Exception as e:
                _backfill_status["running"] = False
                _backfill_status["finished_at"] = datetime.now(UTC).isoformat()
                _backfill_status["error"] = str(e)
                log.error("backfill_failed", symbol=symbol, timeframe=timeframe, error=str(e))

        global _backfill_task
        _backfill_task = asyncio.create_task(_run_backfill())
        log.info("backfill_triggered", symbol=symbol, timeframe=timeframe, days_back=days_back)
        return JSONResponse(
            {"status": "started", "symbol": symbol, "timeframe": timeframe, "days_back": days_back}
        )

    @app.get("/admin/backfill/status", response_class=JSONResponse)
    async def backfill_status_endpoint() -> JSONResponse:
        return JSONResponse(_backfill_status)

    @app.get("/partials/prices", response_class=HTMLResponse)
    async def partial_prices(request: Request) -> HTMLResponse:
        tick = get_price_cache().get("BTCUSDT")
        return templates.TemplateResponse(
            request=request,
            name="partials/prices.html",
            context={"tick": tick},
        )

    @app.get("/partials/signals", response_class=HTMLResponse)
    async def partial_signals(request: Request) -> HTMLResponse:
        results = get_latest_signals()
        computed_at_dt = get_last_computed_at()
        computed_at = computed_at_dt.strftime("%Y-%m-%d %H:%M UTC") if computed_at_dt else None
        return templates.TemplateResponse(
            request=request,
            name="partials/signals.html",
            context={"results": results, "computed_at": computed_at},
        )

    @app.get("/partials/backtest", response_class=HTMLResponse)
    async def partial_backtest(request: Request) -> HTMLResponse:
        results = get_latest_backtest()
        computed_at_dt = get_last_backtest_at()
        computed_at = computed_at_dt.strftime("%Y-%m-%d %H:%M UTC") if computed_at_dt else None
        return templates.TemplateResponse(
            request=request,
            name="partials/backtest.html",
            context={"results": results, "computed_at": computed_at},
        )

    @app.get("/partials/paper_portfolio", response_class=HTMLResponse)
    async def partial_paper_portfolio(request: Request) -> HTMLResponse:
        portfolio = get_portfolio_manager()
        tracker = get_order_tracker()
        snapshot = portfolio.get_snapshot()
        recent_orders = tracker.recent(10)
        return templates.TemplateResponse(
            request=request,
            name="partials/paper_portfolio.html",
            context={"snapshot": snapshot, "recent_orders": recent_orders},
        )

    @app.get("/partials/safety", response_class=HTMLResponse)
    async def partial_safety(request: Request) -> HTMLResponse:
        from trading_bot.config import get_settings
        from trading_bot.feature_flags import is_enabled
        from trading_bot.safety.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker()
        paper_trading_enabled = await is_enabled("paper_trading_enabled")
        risk = get_settings().risk
        return templates.TemplateResponse(
            request=request,
            name="partials/safety.html",
            context={
                "paper_trading_enabled": paper_trading_enabled,
                "cb_tier": cb.current_tier,
                "cb_label": cb.label,
                "cb_drawdown_pct": cb.last_drawdown_pct,
                "cb_peak_tier": cb.peak_tier_today,
                "cb_last_checked": cb.last_checked,
                "t1_pct": risk.tier1_daily_drawdown_pct,
                "t2_pct": risk.tier2_daily_drawdown_pct,
                "t3_pct": risk.tier3_daily_drawdown_pct,
            },
        )

    @app.get("/partials/market_context", response_class=HTMLResponse)
    async def partial_market_context(request: Request) -> HTMLResponse:
        from trading_bot.market_context import get_market_context

        ctx = get_market_context()
        return templates.TemplateResponse(
            request=request,
            name="partials/market_context.html",
            context={"ctx": ctx},
        )

    return app
