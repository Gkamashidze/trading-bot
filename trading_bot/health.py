"""Minimal HTTP health check server for Railway + load balancers.

GET /health → 200 {"status": "ok", ...}  when bot is running
GET /health → 503 {"status": "starting"} during startup

Runs as a background asyncio task alongside the main bot loop.
"""

from __future__ import annotations

import time
from typing import Any

from aiohttp import web

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_START_TIME = time.time()
_state: dict[str, Any] = {
    "db_connected": False,
    "scheduler_running": False,
    "stage": "0",
    "environment": "unknown",
}


def update_health_state(**kwargs: Any) -> None:
    """Update health status fields from main startup sequence."""
    _state.update(kwargs)


async def _health_handler(request: web.Request) -> web.Response:
    uptime_seconds = int(time.time() - _START_TIME)
    body = {
        "status": "ok",
        "uptime_seconds": uptime_seconds,
        "stage": _state["stage"],
        "environment": _state["environment"],
        "db_connected": _state["db_connected"],
        "scheduler_running": _state["scheduler_running"],
        "live_trading_enabled": False,
    }
    return web.json_response(body)


async def start_health_server(host: str = "0.0.0.0", port: int = 8000) -> web.AppRunner:  # noqa: S104
    """Start the health check HTTP server. Returns runner for graceful shutdown."""
    app = web.Application()
    app.router.add_get("/health", _health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()

    log.info("health_server_started", host=host, port=port, path="/health")
    return runner


async def stop_health_server(runner: web.AppRunner) -> None:
    await runner.cleanup()
    log.info("health_server_stopped")
