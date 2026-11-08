"""Production authorization and real database-type response regressions."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from trading_bot.dashboard.app import create_app

KEY = "test-dashboard-credential-long-enough-for-production"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DASHBOARD_API_KEY", KEY)
    return TestClient(create_app())


@pytest.mark.parametrize(
    "path",
    ["/", "/evidence/export/json", "/evidence/export/csv", "/go_live/report", "/partials/audit"],
)
def test_production_reads_require_credentials(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 401
    assert "Basic" in response.headers["www-authenticate"]
    assert client.get(path, params={"x_api_key": KEY}).status_code == 401


def test_missing_production_key_fails_closed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DASHBOARD_API_KEY")
    assert client.get("/evidence/export/json").status_code == 503
    assert client.get("/health").status_code == 200


def test_browser_basic_auth_and_security_headers(client: TestClient) -> None:
    response = client.get("/", auth=("operator", KEY))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-frame-options"] == "DENY"
    assert client.get("/", auth=("wrong-user", KEY)).status_code == 401


def test_basic_auth_mutations_require_same_origin(client: TestClient) -> None:
    response = client.post(
        "/flags/strategy_sma_enabled/toggle",
        auth=("operator", KEY),
        headers={"Origin": "https://untrusted.example"},
        data={"enabled": "true"},
    )
    assert response.status_code == 403


def test_live_trading_cannot_be_enabled_by_dashboard(client: TestClient) -> None:
    response = client.post(
        "/flags/live_trading_enabled/toggle",
        headers={"X-API-Key": KEY},
        data={"enabled": "true"},
    )
    assert response.status_code == 403


def test_flag_update_requires_explicit_value(client: TestClient) -> None:
    response = client.post("/flags/strategy_sma_enabled/toggle", headers={"X-API-Key": KEY})
    assert response.status_code == 422


def test_reports_encode_real_database_values(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from trading_bot import evidence

    sid = uuid.uuid4()
    store = MagicMock()
    row = {
        "session_id": sid,
        "started_at": datetime.now(UTC),
        "paper_capital": Decimal("10000.00000001"),
        "summary_date": date(2026, 11, 8),
    }
    store.get_session_report = AsyncMock(return_value={"session": row})
    store.list_daily_summaries = AsyncMock(return_value=[row])
    monkeypatch.setattr(evidence, "get_evidence_store", lambda: store)
    monkeypatch.setattr(evidence, "get_current_session_id", lambda: sid)
    response = client.get("/evidence/report", headers={"X-API-Key": KEY})
    assert response.status_code == 200
    body = response.json()["session"]
    assert body["session_id"] == str(sid)
    assert body["paper_capital"] == "10000.00000001"
    assert client.get("/evidence/daily", headers={"X-API-Key": KEY}).status_code == 200
