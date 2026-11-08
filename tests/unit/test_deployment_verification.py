"""Startup checks inspect infrastructure without granting trading approval."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from trading_bot.observability import deployment_check


async def test_deployment_checks_are_authenticated_read_only_and_preserve_blockers(monkeypatch):
    methods = []

    def respond(request):
        methods.append(request.method)
        if request.url.path == "/":
            return httpx.Response(401)
        if request.url.path == "/go_live/report":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "criterion_id": "paper_evidence_thresholds",
                            "status": "fail",
                            "blocking": True,
                        }
                    ]
                },
            )
        return httpx.Response(200, json={})

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setenv("DASHBOARD_API_KEY", "test-deployment-check-key-never-used-in-production")
    monkeypatch.setattr(deployment_check.httpx, "AsyncClient", lambda **kwargs: client)
    monkeypatch.setattr("trading_bot.feature_flags.is_enabled", AsyncMock(return_value=False))
    result = await deployment_check.verify_deployment()
    assert result["healthy"]
    assert result["go_live_blockers"] == ["paper_evidence_thresholds"]
    assert set(methods) == {"GET"}


@pytest.mark.parametrize("first", ["dashboard", "shutdown"])
async def test_first_shutdown_completion_stops_the_other_task(monkeypatch, first):
    import asyncio

    from trading_bot import main

    async def dashboard():
        if first == "shutdown":
            await asyncio.Event().wait()

    async def shutdown():
        if first == "dashboard":
            await asyncio.Event().wait()

    monkeypatch.setattr(main, "_run_dashboard", dashboard)
    monkeypatch.setattr(main, "wait_for_shutdown", shutdown)
    monkeypatch.setattr(main, "_startup", AsyncMock(return_value=(None, None, None, None)))
    cleanup = AsyncMock()
    monkeypatch.setattr(main, "_shutdown", cleanup)
    await asyncio.wait_for(main.main_async(), timeout=2)
    cleanup.assert_awaited_once()
