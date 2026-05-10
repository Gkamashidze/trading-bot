"""Tests for BulkheadIsolator."""

from __future__ import annotations

import pytest

from trading_bot.circuit_breakers.bulkhead import BulkheadIsolator, SubsystemState


async def _ok() -> str:
    return "ok"


async def _fail() -> str:
    raise RuntimeError("downstream failure")


def _make(threshold: int = 3, recovery_seconds: float = 30.0) -> BulkheadIsolator:
    return BulkheadIsolator("test", failure_threshold=threshold, recovery_seconds=recovery_seconds)


class TestHealthyBehavior:
    @pytest.mark.asyncio
    async def test_success_returns_result(self) -> None:
        b = _make()
        result = await b.call(_ok)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_state_is_healthy_after_success(self) -> None:
        b = _make()
        await b.call(_ok)
        assert b.state == SubsystemState.HEALTHY
        assert b.consecutive_failures == 0


class TestDegradedBehavior:
    @pytest.mark.asyncio
    async def test_single_failure_raises_and_degrades(self) -> None:
        b = _make(threshold=3)
        with pytest.raises(RuntimeError):
            await b.call(_fail)
        assert b.state == SubsystemState.DEGRADED
        assert b.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_failures_below_threshold_still_raise(self) -> None:
        b = _make(threshold=3)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await b.call(_fail)
        assert b.state == SubsystemState.DEGRADED

    @pytest.mark.asyncio
    async def test_success_after_degraded_resets_to_healthy(self) -> None:
        b = _make(threshold=3)
        with pytest.raises(RuntimeError):
            await b.call(_fail)
        result = await b.call(_ok)
        assert result == "ok"
        assert b.state == SubsystemState.HEALTHY
        assert b.consecutive_failures == 0


class TestIsolatedBehavior:
    @pytest.mark.asyncio
    async def test_isolated_at_threshold(self) -> None:
        b = _make(threshold=2)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await b.call(_fail)
        assert b.state == SubsystemState.ISOLATED

    @pytest.mark.asyncio
    async def test_returns_fallback_when_isolated(self) -> None:
        b = _make(threshold=1, recovery_seconds=9999)
        with pytest.raises(RuntimeError):
            await b.call(_fail)
        # Now isolated — subsequent calls return fallback
        result = await b.call(_fail, fallback="safe")
        assert result == "safe"
        assert b.state == SubsystemState.ISOLATED

    @pytest.mark.asyncio
    async def test_fallback_is_none_by_default(self) -> None:
        b = _make(threshold=1, recovery_seconds=9999)
        with pytest.raises(RuntimeError):
            await b.call(_fail)
        result = await b.call(_fail)
        assert result is None

    @pytest.mark.asyncio
    async def test_recovers_after_window_elapses(self) -> None:
        b = _make(threshold=1, recovery_seconds=0.0)
        with pytest.raises(RuntimeError):
            await b.call(_fail)
        assert b.state == SubsystemState.ISOLATED

        # recovery_seconds=0 means window has already elapsed
        result = await b.call(_ok)
        assert result == "ok"
        assert b.state == SubsystemState.HEALTHY
        assert b.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_probe_failure_stays_isolated(self) -> None:
        b = _make(threshold=1, recovery_seconds=0.0)
        with pytest.raises(RuntimeError):
            await b.call(_fail)
        # probe fires (recovery window=0), but fails again
        result = await b.call(_fail, fallback="safe")
        assert result == "safe"
        assert b.state == SubsystemState.ISOLATED


class TestReset:
    @pytest.mark.asyncio
    async def test_manual_reset_restores_healthy(self) -> None:
        b = _make(threshold=1)
        with pytest.raises(RuntimeError):
            await b.call(_fail)
        assert b.state == SubsystemState.ISOLATED

        b.reset()
        assert b.state == SubsystemState.HEALTHY
        assert b.consecutive_failures == 0

    @pytest.mark.asyncio
    async def test_reset_allows_normal_calls_again(self) -> None:
        b = _make(threshold=1, recovery_seconds=9999)
        with pytest.raises(RuntimeError):
            await b.call(_fail)
        b.reset()
        result = await b.call(_ok)
        assert result == "ok"
