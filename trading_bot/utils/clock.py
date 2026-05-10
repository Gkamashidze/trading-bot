"""Swappable clock abstraction.

Production code uses WallClock. Tests and the backtesting engine inject
FakeClock so time is deterministic and controllable without real sleeps.

Usage:
    # production
    clock: ClockInterface = WallClock()

    # backtesting / tests
    clock = FakeClock(start=datetime(2024, 1, 1, tzinfo=UTC))
    clock.advance(hours=1)
    assert clock.utc_now() == datetime(2024, 1, 1, 1, 0, tzinfo=UTC)
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta


class ClockInterface(ABC):
    """Abstract clock — swap for FakeClock in tests and backtesting."""

    @abstractmethod
    def utc_now(self) -> datetime:
        """Return current time as a UTC-aware datetime."""

    @abstractmethod
    async def sleep(self, seconds: float) -> None:
        """Async sleep for the given number of seconds."""


class WallClock(ClockInterface):
    """Real-world clock backed by the system clock."""

    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class FakeClock(ClockInterface):
    """Deterministic clock for testing and backtesting.

    Time only advances when explicitly called — no real wall-clock time elapses.
    `sleep()` advances the clock instead of blocking, making tests instant.
    """

    def __init__(self, start: datetime) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock start time must be UTC-aware")
        self._now = start.astimezone(UTC)

    def utc_now(self) -> datetime:
        return self._now

    def advance(self, seconds: float = 0.0, **kwargs: float) -> None:
        """Advance the clock forward. Accepts seconds= or timedelta kwargs (hours=, days=, etc.)."""
        self._now += timedelta(seconds=seconds, **kwargs)

    def set(self, dt: datetime) -> None:
        """Jump to a specific point in time."""
        if dt.tzinfo is None:
            raise ValueError("FakeClock.set() requires a UTC-aware datetime")
        self._now = dt.astimezone(UTC)

    async def sleep(self, seconds: float) -> None:
        """Advance the clock instead of blocking — always instant."""
        self.advance(seconds=seconds)
