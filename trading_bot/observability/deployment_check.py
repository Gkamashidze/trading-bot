"""Read-only HTTP verification from inside a newly deployed service.

The service can use its dashboard secret without exposing it to CI or logs.
This verifies infrastructure; a successful check never authorizes live trading.
"""

from __future__ import annotations

import asyncio
import os

import httpx

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_PATHS = (
    "/readyz",
    "/evidence/report",
    "/evidence/daily",
    "/evidence/weekly",
    "/go_live/report",
    "/partials/prices",
    "/partials/jobs",
    "/partials/paper_portfolio",
    "/partials/alpaca_account",
    "/partials/safety",
    "/partials/promotion_progress",
)


async def verify_deployment() -> dict[str, object]:
    """Probe authenticated reports and anonymous denial; never submit orders or change flags."""
    base = f"http://127.0.0.1:{int(os.environ.get('PORT', '8000'))}"
    key = os.environ.get("DASHBOARD_API_KEY", "")
    failures: list[str] = []
    blocking: list[str] = []
    async with httpx.AsyncClient(timeout=30) as client:
        for _ in range(30):
            try:
                if (await client.get(base + "/readyz")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
        for path in _PATHS:
            try:
                response = await client.get(base + path, headers={"X-API-Key": key})
                if response.status_code != 200:
                    failures.append(f"{path}: HTTP {response.status_code}")
                elif path == "/go_live/report":
                    blocking = [
                        item["criterion_id"]
                        for item in response.json()["results"]
                        if item["blocking"] and item["status"] != "pass"
                    ]
            except (httpx.HTTPError, ValueError, KeyError):
                failures.append(f"{path}: request or response failed")
        try:
            if (await client.get(base + "/")).status_code != 401:
                failures.append("anonymous dashboard access was not denied")
        except httpx.HTTPError:
            failures.append("anonymous authentication probe failed")
    from trading_bot.feature_flags import is_enabled
    from trading_bot.promotion.micro_live import MicroLiveGate

    if await is_enabled("live_trading_enabled") or MicroLiveGate._MICRO_LIVE_GLOBALLY_ENABLED:
        failures.append("real-money execution must remain disabled")
    result: dict[str, object] = {
        "healthy": not failures,
        "failures": failures,
        "go_live_blockers": blocking,
        "checked_routes": len(_PATHS),
        "commit": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown"),
    }
    if failures:
        log.error("deployment_verification_complete", **result)
    else:
        log.info("deployment_verification_complete", **result)
    return result
