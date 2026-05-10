"""Tests for ClockInterface, WallClock, and FakeClock."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest

from trading_bot.utils.clock import FakeClock, WallClock


class TestWallClock:
    def test_utc_now_is_utc_aware(self) -> None:
        clock = WallClock()
        now = clock.utc_now()
        assert now.tzinfo is not None
        assert now.utcoffset().total_seconds() == 0  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_sleep_advances_real_time(self) -> None:
        clock = WallClock()
        before = clock.utc_now()
        await clock.sleep(0.01)
        after = clock.utc_now()
        assert after > before


class TestFakeClock:
    _START = datetime(2024, 1, 1, tzinfo=UTC)

    def _make(self) -> FakeClock:
        return FakeClock(start=self._START)

    def test_naive_start_raises(self) -> None:
        with pytest.raises(ValueError, match="UTC-aware"):
            FakeClock(start=datetime(2024, 1, 1))  # noqa: DTZ001

    def test_utc_now_returns_start(self) -> None:
        clock = self._make()
        assert clock.utc_now() == self._START

    def test_advance_seconds(self) -> None:
        clock = self._make()
        clock.advance(seconds=3600)
        assert clock.utc_now() == datetime(2024, 1, 1, 1, 0, 0, tzinfo=UTC)

    def test_advance_days_kwarg(self) -> None:
        clock = self._make()
        clock.advance(days=1)
        assert clock.utc_now() == datetime(2024, 1, 2, tzinfo=UTC)

    def test_advance_is_cumulative(self) -> None:
        clock = self._make()
        clock.advance(seconds=30)
        clock.advance(seconds=30)
        assert clock.utc_now() == datetime(2024, 1, 1, 0, 1, 0, tzinfo=UTC)

    def test_set_jumps_to_exact_time(self) -> None:
        clock = self._make()
        target = datetime(2025, 6, 15, 12, 0, tzinfo=UTC)
        clock.set(target)
        assert clock.utc_now() == target

    def test_set_naive_raises(self) -> None:
        clock = self._make()
        with pytest.raises(ValueError, match="UTC-aware"):
            clock.set(datetime(2025, 1, 1))  # noqa: DTZ001

    @pytest.mark.asyncio
    async def test_sleep_advances_clock_not_wall_time(self) -> None:
        clock = self._make()
        wall_before = time.perf_counter()
        await clock.sleep(3600)  # 1 fake hour
        wall_elapsed = time.perf_counter() - wall_before

        assert clock.utc_now() == datetime(2024, 1, 1, 1, 0, 0, tzinfo=UTC)
        assert wall_elapsed < 0.1  # real time barely passed
