"""Tests for state/risk_state.py — InMemoryRiskStateStore."""

from decimal import Decimal

import pytest

from trading_bot.state.risk_state import (
    EmergencyHaltReason,
    InMemoryRiskStateStore,
    get_risk_state_store,
    set_risk_state_store,
)


class TestInMemoryRiskStateStore:
    @pytest.mark.asyncio
    async def test_initial_state_is_safe(self) -> None:
        store = InMemoryRiskStateStore()
        snap = await store.get_snapshot()
        assert not snap.kill_switch_active
        assert not snap.emergency_halt_active
        assert not snap.reconciler_block_active
        assert not snap.is_trading_globally_blocked

    @pytest.mark.asyncio
    async def test_kill_switch_activate_deactivate(self) -> None:
        store = InMemoryRiskStateStore()
        await store.activate_kill_switch("test", "alice")
        snap = await store.get_snapshot()
        assert snap.kill_switch_active
        assert snap.kill_switch_reason == "test"
        assert snap.kill_switch_activated_by == "alice"

        await store.deactivate_kill_switch("bob")
        snap2 = await store.get_snapshot()
        assert not snap2.kill_switch_active

    @pytest.mark.asyncio
    async def test_emergency_halt(self) -> None:
        store = InMemoryRiskStateStore()
        await store.activate_emergency_halt(EmergencyHaltReason.LOSS_LIMIT_BREACH, "system")
        snap = await store.get_snapshot()
        assert snap.emergency_halt_active
        assert snap.emergency_halt_reason == EmergencyHaltReason.LOSS_LIMIT_BREACH
        assert snap.is_trading_globally_blocked

        await store.clear_emergency_halt("alice")
        snap2 = await store.get_snapshot()
        assert not snap2.emergency_halt_active

    @pytest.mark.asyncio
    async def test_reconciler_block(self) -> None:
        store = InMemoryRiskStateStore()
        await store.set_reconciler_block(True, "mismatch detected", "reconciler")
        snap = await store.get_snapshot()
        assert snap.reconciler_block_active
        assert snap.is_trading_globally_blocked

        await store.set_reconciler_block(False, "", "operator")
        snap2 = await store.get_snapshot()
        assert not snap2.reconciler_block_active

    @pytest.mark.asyncio
    async def test_strategy_state(self) -> None:
        store = InMemoryRiskStateStore()
        await store.set_strategy_state("sma_cross", "paused", "alice")
        snap = await store.get_snapshot()
        assert snap.strategy_states["sma_cross"] == "paused"

    @pytest.mark.asyncio
    async def test_record_daily_loss(self) -> None:
        store = InMemoryRiskStateStore()
        await store.record_loss(Decimal("100"), "daily")
        await store.record_loss(Decimal("50"), "daily")
        snap = await store.get_snapshot()
        assert snap.daily_loss_usd == Decimal("150")

    @pytest.mark.asyncio
    async def test_reset_loss_budget(self) -> None:
        store = InMemoryRiskStateStore()
        await store.record_loss(Decimal("500"), "daily")
        await store.reset_loss_budget("daily", "scheduler")
        snap = await store.get_snapshot()
        assert snap.daily_loss_usd == Decimal("0")

    @pytest.mark.asyncio
    async def test_capital_override(self) -> None:
        store = InMemoryRiskStateStore()
        await store.set_capital_override("sma", 0.10, "alice")
        snap = await store.get_snapshot()
        assert snap.capital_allocation_overrides["sma"] == 0.10

        await store.set_capital_override("sma", None, "alice")
        snap2 = await store.get_snapshot()
        assert "sma" not in snap2.capital_allocation_overrides

    @pytest.mark.asyncio
    async def test_operator_lock(self) -> None:
        store = InMemoryRiskStateStore()
        await store.set_operator_lock("BTC/USDT", "maintenance by alice", "alice")
        snap = await store.get_snapshot()
        assert "BTC/USDT" in snap.operator_locks

        await store.clear_operator_lock("BTC/USDT", "alice")
        snap2 = await store.get_snapshot()
        assert "BTC/USDT" not in snap2.operator_locks

    @pytest.mark.asyncio
    async def test_version_increments_on_mutation(self) -> None:
        store = InMemoryRiskStateStore()
        v0 = (await store.get_snapshot()).version
        await store.activate_kill_switch("test", "alice")
        v1 = (await store.get_snapshot()).version
        assert v1 > v0

    @pytest.mark.asyncio
    async def test_get_snapshot_returns_copy(self) -> None:
        store = InMemoryRiskStateStore()
        snap1 = await store.get_snapshot()
        snap1.strategy_states["injected"] = "paused"
        snap2 = await store.get_snapshot()
        assert "injected" not in snap2.strategy_states

    def test_singleton_getter_returns_instance(self) -> None:
        store = InMemoryRiskStateStore()
        set_risk_state_store(store)
        assert get_risk_state_store() is store
