"""Tests for Stage 6 Safety Layer: CircuitBreaker."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.safety.circuit_breaker import CircuitBreaker


def _make_snapshot(daily_drawdown_pct: float) -> MagicMock:
    snap = MagicMock()
    snap.daily_drawdown_pct = Decimal(str(daily_drawdown_pct))
    return snap


def _make_portfolio(drawdown: float) -> MagicMock:
    pm = MagicMock()
    pm.get_snapshot.return_value = _make_snapshot(drawdown)
    return pm


class TestCircuitBreakerTierComputation:
    def test_healthy_below_tier1(self) -> None:
        cb = CircuitBreaker()
        tier = cb._compute_tier(0.03, 0.05, 0.10, 0.15)
        assert tier == 0

    def test_tier1_at_threshold(self) -> None:
        cb = CircuitBreaker()
        tier = cb._compute_tier(0.05, 0.05, 0.10, 0.15)
        assert tier == 1

    def test_tier2_at_threshold(self) -> None:
        cb = CircuitBreaker()
        tier = cb._compute_tier(0.10, 0.05, 0.10, 0.15)
        assert tier == 2

    def test_tier3_at_threshold(self) -> None:
        cb = CircuitBreaker()
        tier = cb._compute_tier(0.15, 0.05, 0.10, 0.15)
        assert tier == 3

    def test_tier3_above_threshold(self) -> None:
        cb = CircuitBreaker()
        tier = cb._compute_tier(0.20, 0.05, 0.10, 0.15)
        assert tier == 3


class TestCircuitBreakerCheck:
    @pytest.mark.asyncio
    async def test_healthy_portfolio_tier_zero(self) -> None:
        cb = CircuitBreaker()
        pm = _make_portfolio(-0.01)  # -1% drawdown
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            tier = await cb.check()
        assert tier == 0
        assert cb.current_tier == 0
        assert cb.is_trading_allowed() is True

    @pytest.mark.asyncio
    async def test_tier1_breach_detected(self) -> None:
        cb = CircuitBreaker()
        pm = _make_portfolio(-0.06)  # -6%
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            with patch(
                "trading_bot.safety.circuit_breaker._send_tier_alert", new_callable=AsyncMock
            ):
                tier = await cb.check()
        assert tier == 1
        assert cb.current_tier == 1
        assert cb.is_trading_allowed() is True  # tier 1 still allows trading

    @pytest.mark.asyncio
    async def test_tier2_blocks_trading(self) -> None:
        cb = CircuitBreaker()
        pm = _make_portfolio(-0.11)  # -11%
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            with patch(
                "trading_bot.safety.circuit_breaker._send_tier_alert", new_callable=AsyncMock
            ):
                tier = await cb.check()
        assert tier == 2
        assert cb.is_trading_allowed() is False

    @pytest.mark.asyncio
    async def test_tier3_blocks_trading(self) -> None:
        cb = CircuitBreaker()
        pm = _make_portfolio(-0.16)  # -16%
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            with patch(
                "trading_bot.safety.circuit_breaker._send_tier_alert", new_callable=AsyncMock
            ):
                tier = await cb.check()
        assert tier == 3
        assert cb.is_trading_allowed() is False

    @pytest.mark.asyncio
    async def test_peak_tier_tracks_highest(self) -> None:
        cb = CircuitBreaker()
        pm_t1 = _make_portfolio(-0.06)
        pm_t2 = _make_portfolio(-0.11)
        pm_healthy = _make_portfolio(-0.01)

        with patch("trading_bot.safety.circuit_breaker._send_tier_alert", new_callable=AsyncMock):
            with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm_t1):
                await cb.check()
            with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm_t2):
                await cb.check()
            with patch(
                "trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm_healthy
            ):
                await cb.check()

        assert cb.peak_tier_today == 2
        assert cb.current_tier == 0  # recovered, but peak was 2

    @pytest.mark.asyncio
    async def test_last_checked_set_after_check(self) -> None:
        cb = CircuitBreaker()
        assert cb.last_checked is None
        pm = _make_portfolio(-0.01)
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            await cb.check()
        assert cb.last_checked is not None

    @pytest.mark.asyncio
    async def test_tripped_at_set_on_first_breach(self) -> None:
        cb = CircuitBreaker()
        assert cb.tripped_at is None
        pm = _make_portfolio(-0.06)
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.create_task = MagicMock()
                await cb.check()
        assert cb.tripped_at is not None


class TestCircuitBreakerReset:
    @pytest.mark.asyncio
    async def test_reset_day_holds_tier1_when_drawdown_still_above_threshold(self) -> None:
        """Drawdown still 11% at midnight — breaker stays at tier 1, not tier 0."""
        cb = CircuitBreaker()
        pm = _make_portfolio(-0.11)
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.create_task = MagicMock()
                await cb.check()

        assert cb.current_tier == 2
        cb.reset_day()
        # 11% drawdown >= tier-1 threshold (5%) → stays at tier 1 (not 0)
        assert cb.current_tier == 1
        assert cb.peak_tier_today == 0
        assert cb.tripped_at is None
        assert cb.is_trading_allowed() is True  # tier 1 still allows trading

    @pytest.mark.asyncio
    async def test_reset_day_clears_to_tier0_when_recovered(self) -> None:
        """Drawdown recovered to 2% — breaker fully clears at midnight."""
        cb = CircuitBreaker()
        pm = _make_portfolio(-0.02)
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.create_task = MagicMock()
                await cb.check()

        assert cb.current_tier == 0
        cb.reset_day()
        assert cb.current_tier == 0
        assert cb.is_trading_allowed() is True

    def test_reset_day_on_fresh_breaker_is_noop(self) -> None:
        cb = CircuitBreaker()
        cb.reset_day()
        assert cb.current_tier == 0


class TestCircuitBreakerLabels:
    def test_label_healthy(self) -> None:
        cb = CircuitBreaker()
        assert "ჯანმრთელი" in cb.label

    @pytest.mark.asyncio
    async def test_label_tier1(self) -> None:
        cb = CircuitBreaker()
        pm = _make_portfolio(-0.06)
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            with patch("asyncio.get_event_loop") as mock_loop:
                mock_loop.return_value.create_task = MagicMock()
                await cb.check()
        assert "I" in cb.label
