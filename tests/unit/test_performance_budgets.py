"""Tests for performance budget enforcement."""

from __future__ import annotations

import asyncio

import pytest

from trading_bot.observability.budgets import BUDGETS_MS, budget


class TestBudgetContextManager:
    @pytest.mark.asyncio
    async def test_completes_within_budget(self) -> None:
        async with budget("risk_check", budget_ms=1000.0):
            pass  # instant — well within budget

    @pytest.mark.asyncio
    async def test_uses_budgets_ms_table_by_default(self) -> None:
        async with budget("risk_check"):  # resolves via BUDGETS_MS
            pass

    @pytest.mark.asyncio
    async def test_unknown_subsystem_no_crash(self) -> None:
        async with budget("completely_unknown_subsystem"):
            pass

    @pytest.mark.asyncio
    async def test_code_inside_still_runs_after_violation(self) -> None:
        executed = False
        async with budget("risk_check", budget_ms=0.001):
            await asyncio.sleep(0.005)
            executed = True
        assert executed

    @pytest.mark.asyncio
    async def test_exception_inside_propagates(self) -> None:
        with pytest.raises(ValueError, match="inner error"):
            async with budget("signal_generation", budget_ms=1000.0):
                raise ValueError("inner error")

    def test_budgets_ms_contains_required_subsystems(self) -> None:
        required = {"risk_check", "signal_generation", "order_submit", "signal_to_order"}
        for key in required:
            assert key in BUDGETS_MS, f"Missing budget for subsystem: {key}"
            assert BUDGETS_MS[key] > 0

    def test_risk_check_budget_is_tight(self) -> None:
        assert BUDGETS_MS["risk_check"] <= 10.0  # must be fast — pre-trade gate
