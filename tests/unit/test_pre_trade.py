"""Tests for compliance/pre_trade.py — PreTradeChecklist."""

from decimal import Decimal

import pytest

from trading_bot.compliance.pre_trade import (
    CheckId,
    PreTradeChecklist,
    PreTradeChecklistConfig,
    PreTradeContext,
    build_paper_context,
)


def _all_clear_context(**overrides: object) -> PreTradeContext:
    ctx = PreTradeContext(
        symbol="BTC/USDT",
        strategy_id="sma_cross",
        order_qty=Decimal("0.001"),
        order_notional=Decimal("50"),
        kill_switch_active=False,
        market_is_open=True,
        in_blackout_window=False,
        market_data_age_seconds=5.0,
        order_book_age_ms=100.0,
        reconciler_is_clean=True,
        risk_state_healthy=True,
        circuit_breakers_clear=True,
        capital_policy_allows=True,
        strategy_is_approved=True,
        symbol_is_tradable=True,
        order_size_within_limits=True,
        live_mode_enabled=True,
    )
    for k, v in overrides.items():
        object.__setattr__(ctx, k, v)
    return ctx


class TestPreTradeChecklist:
    def setup_method(self) -> None:
        self.checklist = PreTradeChecklist(config=PreTradeChecklistConfig())

    @pytest.mark.asyncio
    async def test_all_clear_passes(self) -> None:
        result = await self.checklist.run(_all_clear_context())
        assert result.passed
        assert not result.failing_checks

    @pytest.mark.asyncio
    async def test_kill_switch_blocks(self) -> None:
        result = await self.checklist.run(_all_clear_context(kill_switch_active=True))
        assert not result.passed
        assert CheckId.KILL_SWITCH_OFF in result.failing_checks

    @pytest.mark.asyncio
    async def test_none_kill_switch_fails_closed(self) -> None:
        result = await self.checklist.run(_all_clear_context(kill_switch_active=None))
        assert not result.passed
        assert CheckId.KILL_SWITCH_OFF in result.failing_checks

    @pytest.mark.asyncio
    async def test_live_mode_disabled_blocks(self) -> None:
        result = await self.checklist.run(_all_clear_context(live_mode_enabled=False))
        assert not result.passed
        assert CheckId.LIVE_MODE_ENABLED in result.failing_checks

    @pytest.mark.asyncio
    async def test_stale_market_data_blocks(self) -> None:
        result = await self.checklist.run(_all_clear_context(market_data_age_seconds=120.0))
        assert not result.passed
        assert CheckId.FRESH_MARKET_DATA in result.failing_checks

    @pytest.mark.asyncio
    async def test_stale_order_book_blocks(self) -> None:
        result = await self.checklist.run(_all_clear_context(order_book_age_ms=1000.0))
        assert not result.passed
        assert CheckId.FRESH_ORDER_BOOK in result.failing_checks

    @pytest.mark.asyncio
    async def test_reconciler_unclean_blocks(self) -> None:
        result = await self.checklist.run(_all_clear_context(reconciler_is_clean=False))
        assert not result.passed
        assert CheckId.RECONCILER_CLEAN in result.failing_checks

    @pytest.mark.asyncio
    async def test_circuit_breaker_tripped_blocks(self) -> None:
        result = await self.checklist.run(_all_clear_context(circuit_breakers_clear=False))
        assert not result.passed
        assert CheckId.CIRCUIT_BREAKERS_CLEAR in result.failing_checks

    @pytest.mark.asyncio
    async def test_multiple_failures_all_reported(self) -> None:
        result = await self.checklist.run(
            _all_clear_context(
                kill_switch_active=True,
                reconciler_is_clean=False,
                risk_state_healthy=False,
            )
        )
        assert not result.passed
        assert CheckId.KILL_SWITCH_OFF in result.failing_checks
        assert CheckId.RECONCILER_CLEAN in result.failing_checks
        assert CheckId.RISK_STATE_HEALTHY in result.failing_checks

    @pytest.mark.asyncio
    async def test_paper_config_skips_live_mode_and_book(self) -> None:
        cfg = PreTradeChecklistConfig(require_live_mode_flag=False, require_order_book=False)
        checklist = PreTradeChecklist(config=cfg)
        ctx = build_paper_context(
            symbol="BTC/USDT",
            strategy_id="s",
            order_qty=Decimal("0.001"),
            order_notional=Decimal("50"),
            kill_switch_active=False,
            market_data_age_seconds=5.0,
            reconciler_is_clean=True,
            risk_state_healthy=True,
            circuit_breakers_clear=True,
            capital_policy_allows=True,
            strategy_is_approved=True,
            symbol_is_tradable=True,
            order_size_within_limits=True,
        )
        result = await checklist.run(ctx)
        assert result.passed

    @pytest.mark.asyncio
    async def test_summary_includes_count(self) -> None:
        result = await self.checklist.run(_all_clear_context())
        assert "OK" in result.summary
