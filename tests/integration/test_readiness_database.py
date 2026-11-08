"""Real PostgreSQL checks for concurrent audit writes and atomic dashboard changes.

Uses a disposable schema and TEST_DATABASE_URL, never the production DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import httpx
import pytest
import pytest_asyncio

from trading_bot.database.audit_log import PostgresAuditLog

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def database():
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL tests")
    schema = "readiness_" + uuid.uuid4().hex
    admin = await asyncpg.connect(url)
    await admin.execute(f'CREATE SCHEMA "{schema}"')
    pool = await asyncpg.create_pool(
        url, min_size=1, max_size=10, server_settings={"search_path": schema + ",public"}
    )
    for table in (
        "audit_log",
        "feature_flags",
        "risk_state",
        "paper_orders",
        "idempotency_keys",
        "evidence_sessions",
        "evidence_tca_records",
        "evidence_accounting_records",
        "evidence_portfolio_snapshots",
        "go_live_approvals",
    ):
        await admin.execute(f'CREATE TABLE "{schema}".{table} (LIKE public.{table} INCLUDING ALL)')
    try:
        yield pool
    finally:
        await pool.close()
        await admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
        await admin.close()


async def test_concurrent_events_form_one_verified_chain(database):
    audit = PostgresAuditLog(database)
    await asyncio.gather(
        *(
            audit.append("test.concurrent", {"z": i, "a": {"second": 2, "first": 1}})
            for i in range(50)
        )
    )
    assert await audit.verify_chain()
    async with database.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM audit_log") == 50


@pytest.mark.parametrize("column,value", [("actor", "changed"), ("prev_event_hash", "fork")])
async def test_metadata_tampering_and_forks_are_detected(database, column, value):
    audit = PostgresAuditLog(database)
    await audit.append("test.integrity", {"amount": "10"}, actor="operator")
    async with database.acquire() as conn:
        await conn.execute(f"UPDATE audit_log SET {column} = $1", value)
    assert not await audit.verify_chain()


async def test_audit_event_rolls_back_with_state_transaction(database):
    audit = PostgresAuditLog(database)
    with pytest.raises(RuntimeError, match="rollback"):
        async with database.acquire() as conn:
            async with conn.transaction():
                await audit.append("test.rollback", {"value": 1}, connection=conn)
                raise RuntimeError("rollback")
    assert await audit.get_chain_head() is None
    await audit.append("test.after_rollback", {"value": 2})
    assert await audit.verify_chain()


async def test_retrying_explicit_flag_update_is_idempotent(database, monkeypatch):
    from trading_bot.dashboard import app

    key = "integration-dashboard-key-for-local-database-tests"
    monkeypatch.setenv("DASHBOARD_API_KEY", key)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(app, "_pool", database)
    async with database.acquire() as conn:
        await conn.execute(
            "INSERT INTO feature_flags (flag_name, enabled) VALUES ('test_flag', false)"
        )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app.create_app()), base_url="http://test"
    ) as client:
        for _ in range(2):
            response = await client.post(
                "/flags/test_flag/toggle", data={"enabled": "true"}, headers={"X-API-Key": key}
            )
            assert response.status_code == 200
    async with database.acquire() as conn:
        assert await conn.fetchval("SELECT enabled FROM feature_flags WHERE flag_name='test_flag'")
        assert await conn.fetchval("SELECT count(*) FROM audit_log") == 1
    assert await PostgresAuditLog(database).verify_chain()


async def test_risk_halts_and_json_state_survive_new_store_instances(database):
    from trading_bot.state.risk_state import PostgresRiskStateStore

    first = PostgresRiskStateStore(database)
    await first._ensure_row()
    await first.set_strategy_state("sma", "paused", actor="operator")
    await first.activate_kill_switch("maintenance", actor="operator")
    restored = await PostgresRiskStateStore(database).get_snapshot()
    assert restored.is_trading_globally_blocked
    assert restored.strategy_states == {"sma": "paused"}


async def test_paper_round_trip_records_real_fees_and_blocks_cross_strategy_and_restart_duplicates(
    database, monkeypatch, tmp_path
):
    from datetime import UTC, datetime
    from decimal import Decimal

    from trading_bot.accounting import ledger
    from trading_bot.backtesting.fill_model import FillModelProfile
    from trading_bot.core.models import PriceTick
    from trading_bot.evidence import store as evidence_module
    from trading_bot.evidence.performance import capture_strategy_equity
    from trading_bot.evidence.store import EvidenceStore
    from trading_bot.execution import router
    from trading_bot.execution.paper import PaperExchange
    from trading_bot.feature_flags import store as flags
    from trading_bot.idempotency import decorator
    from trading_bot.idempotency.store import PostgresIdempotencyStore
    from trading_bot.oms import reconciler, tracker
    from trading_bot.portfolio import manager
    from trading_bot.state import risk_state
    from trading_bot.strategies.base import StrategyResult
    from trading_bot.websocket import price_cache

    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setattr(manager, "_manager", manager.PortfolioManager(Decimal("10000")))
    monkeypatch.setattr(ledger, "_ledger", ledger.AccountingLedger())
    monkeypatch.setattr(flags, "_default_store", flags.FeatureFlagStore(database))
    monkeypatch.setattr(decorator, "_default_store", PostgresIdempotencyStore(database))
    monkeypatch.setattr(reconciler, "get_reconciler", lambda: None)
    order_tracker = tracker.OrderTracker()
    order_tracker.set_pool(database)
    monkeypatch.setattr(tracker, "_tracker", order_tracker)
    state = risk_state.PostgresRiskStateStore(database)
    await state._ensure_row()
    monkeypatch.setattr(risk_state, "_risk_state_store", state)
    monkeypatch.setattr(router, "_last_signal", {})
    monkeypatch.setattr(router, "_ROUTE_LOCK", asyncio.Lock())
    monkeypatch.setattr(router, "_LAST_SIGNAL_PATH", tmp_path / "signals.json")
    monkeypatch.setattr(router, "_exchange", PaperExchange(FillModelProfile.IDEAL))
    cache = price_cache.PriceCache()
    monkeypatch.setattr(price_cache, "_cache", cache)
    evidence = EvidenceStore(database)
    session = await evidence.start_session("test", {}, Decimal("10000"), ["BTC/USDT"], ["sma"])
    monkeypatch.setattr(evidence_module, "_store", evidence)
    monkeypatch.setattr(evidence_module, "_current_session_id", session.session_id)

    async def price(value):
        await cache.update(
            PriceTick(
                symbol="BTCUSDT",
                price=Decimal(value),
                open_24h=Decimal(value),
                high_24h=Decimal(value),
                low_24h=Decimal(value),
                volume_24h=Decimal("100"),
                timestamp=datetime.now(UTC),
            )
        )

    await price("50000")
    buy = StrategyResult(strategy_id="sma", symbol="BTC/USDT", signal="BUY", strength=1)
    await asyncio.gather(
        router.route_signal(buy),
        router.route_signal(buy.model_copy(update={"strategy_id": "rsi"})),
    )
    assert manager.get_portfolio_manager().get_snapshot().cash_balance == Decimal("8000")
    await price("51000")
    wrong_owner = StrategyResult(strategy_id="rsi", symbol="BTC/USDT", signal="SELL", strength=1)
    await router.route_signal(wrong_owner)
    assert len(order_tracker.recent()) == 1
    await router.route_signal(buy.model_copy(update={"signal": "SELL"}))
    assert manager.get_portfolio_manager().get_snapshot().cash_balance == Decimal("10040")
    monkeypatch.setattr(router, "_last_signal", {})  # process restart loses memory
    await router.route_signal(buy)
    assert len(order_tracker.recent()) == 2
    async with asyncio.timeout(3):
        while True:
            async with database.acquire() as conn:
                if await conn.fetchval("SELECT count(*) FROM paper_orders") == 2:
                    break
            await asyncio.sleep(0.01)
    assert await evidence.count_round_trips(session.session_id) == 1
    books = await capture_strategy_equity(database, session.session_id)
    assert books["sma"]["complete"]
    assert Decimal(books["sma"]["equity"]) == Decimal("10040")


async def test_operator_approval_retry_persists_once_with_atomic_audit(database):
    from unittest.mock import AsyncMock

    from trading_bot.go_live.gate import GoLiveGate

    flags = AsyncMock()
    flags.is_enabled.side_effect = lambda name: name != "live_trading_enabled"
    exchange = AsyncMock()
    exchange.health_check.return_value = True
    audit = PostgresAuditLog(database)
    gate = GoLiveGate(
        audit_log=audit,
        exchange=exchange,
        pool=database,
        feature_flags=flags,
        paper_trading_days=40,
        paper_round_trips=120,
        paper_win_rate=0.6,
        paper_drawdown_pct=0.05,
        backtest_win_rate=0.6,
        backtest_drawdown_pct=0.08,
        reconciler_last_run_clean=True,
        rollback_runbook_exists=True,
        exchange_permissions_verified=True,
        audit_chain_verified=True,
    )
    first = await gate.record_approval(
        operator="test-operator",
        rollback_plan_confirmed=True,
        risk_sign_off_by="test-reviewer",
        correlation_id="request-1",
    )
    second = await gate.record_approval(
        operator="test-operator",
        rollback_plan_confirmed=True,
        risk_sign_off_by="test-reviewer",
        correlation_id="request-1",
    )
    assert first.approval_id == second.approval_id
    async with database.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM go_live_approvals") == 1
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM audit_log WHERE event_type='go_live.operator_approved'"
            )
            == 1
        )
    assert await audit.verify_chain()
