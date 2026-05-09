"""FastAPI dashboard application.

Routes:
    GET /                         - Main dashboard page (full HTML)
    GET /partials/status          - htmx partial: system status card
    GET /partials/flags           - htmx partial: feature flags card
    GET /partials/jobs            - htmx partial: scheduler jobs card
    GET /partials/audit           - htmx partial: recent audit log entries
    GET /health                   - JSON health check (Railway healthcheck)
    POST /flags/{name}/toggle     - Toggle a feature flag on/off
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Set by init_dashboard() after DB + scheduler are ready
_pool: Any = None
_scheduler: Any = None
_start_time = time.time()


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
            "stage": "0",
            "live_trading_enabled": False,
        }

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request, name="index.html"
        )

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
                "stage": "0",
            },
        )

    @app.get("/partials/flags", response_class=HTMLResponse)
    async def partial_flags(request: Request) -> HTMLResponse:
        flags: list[dict[str, Any]] = []
        if _pool is not None:
            try:
                async with _pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT name, enabled, description FROM feature_flags ORDER BY name"
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
                        """SELECT event_type, actor, details, created_at
                           FROM audit_log
                           ORDER BY created_at DESC
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
                       SET enabled = NOT enabled, updated_at = NOW()
                       WHERE name = $1
                       RETURNING name, enabled, description""",
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

    return app
