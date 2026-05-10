"""Bulkhead isolator — prevent cascading failures across subsystem boundaries.

Each subsystem (WebSocket, OMS, RiskEngine, DataFeed, etc.) wraps its
outbound calls through a BulkheadIsolator. When consecutive failures exceed
the threshold the subsystem is ISOLATED and calls return a safe fallback
instead of propagating exceptions upward.

After `recovery_seconds` the isolator enters HALF_OPEN state and lets one
probe call through. Success → HEALTHY. Failure → back to ISOLATED.

State machine:
    HEALTHY ──(failures < threshold)──► DEGRADED
    DEGRADED ──(failures >= threshold)──► ISOLATED
    ISOLATED ──(recovery window elapsed)──► HALF_OPEN
    HALF_OPEN ──(probe success)──► HEALTHY
    HALF_OPEN ──(probe failure)──► ISOLATED
    any ──(manual reset)──► HEALTHY

Usage:
    ws_bulkhead = BulkheadIsolator("websocket", failure_threshold=3)
    result = await ws_bulkhead.call(risky_coroutine, arg1, fallback=None)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeVar

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T")


class SubsystemState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # failures accumulating, below threshold
    ISOLATED = "isolated"  # threshold exceeded — calls return fallback
    HALF_OPEN = "half_open"  # recovery probe in flight


class BulkheadIsolator:
    """Per-subsystem failure domain isolator.

    All state mutations happen in the asyncio event loop (single-threaded),
    so no locking is required.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_seconds: float = 30.0,
    ) -> None:
        self._name = name
        self._threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._consecutive_failures = 0
        self._state = SubsystemState.HEALTHY
        self._isolated_at: datetime | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def call(
        self,
        coro_fn: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: T | None = None,
        **kwargs: Any,
    ) -> T | None:
        """Execute coro_fn with bulkhead protection.

        Returns fallback when ISOLATED and the recovery window has not elapsed.
        Raises the underlying exception when DEGRADED (threshold not yet hit).
        """
        if self._state == SubsystemState.ISOLATED:
            if not self._recovery_window_elapsed():
                log.warning(
                    "bulkhead_call_blocked",
                    subsystem=self._name,
                    consecutive_failures=self._consecutive_failures,
                )
                return fallback
            # Recovery window elapsed — allow one probe
            self._state = SubsystemState.HALF_OPEN

        # Track whether this is a recovery probe so we suppress the exception
        # (HALF_OPEN → failure → back to ISOLATED, caller gets fallback).
        # Regular calls always raise so the caller knows something went wrong.
        is_probe = self._state == SubsystemState.HALF_OPEN

        try:
            result = await coro_fn(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure(exc)
            if is_probe:
                # Probe failed — already back to ISOLATED; suppress for caller
                return fallback
            raise

    def reset(self) -> None:
        """Manually restore HEALTHY state (operator action)."""
        self._consecutive_failures = 0
        self._state = SubsystemState.HEALTHY
        self._isolated_at = None
        log.info("bulkhead_manually_reset", subsystem=self._name)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def state(self) -> SubsystemState:
        return self._state

    @property
    def name(self) -> str:
        return self._name

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_success(self) -> None:
        if self._state != SubsystemState.HEALTHY:
            log.info(
                "bulkhead_recovered",
                subsystem=self._name,
                previous_state=self._state,
            )
        self._consecutive_failures = 0
        self._state = SubsystemState.HEALTHY
        self._isolated_at = None

    def _on_failure(self, exc: Exception) -> None:
        self._consecutive_failures += 1

        if self._consecutive_failures >= self._threshold:
            if self._state not in (SubsystemState.ISOLATED, SubsystemState.HALF_OPEN):
                self._isolated_at = datetime.now(UTC)
                log.error(
                    "bulkhead_subsystem_isolated",
                    subsystem=self._name,
                    consecutive_failures=self._consecutive_failures,
                    threshold=self._threshold,
                    error=str(exc),
                )
            self._state = SubsystemState.ISOLATED
        else:
            self._state = SubsystemState.DEGRADED
            log.warning(
                "bulkhead_failure_recorded",
                subsystem=self._name,
                consecutive_failures=self._consecutive_failures,
                threshold=self._threshold,
                error=str(exc),
            )

    def _recovery_window_elapsed(self) -> bool:
        if self._isolated_at is None:
            return True
        elapsed = (datetime.now(UTC) - self._isolated_at).total_seconds()
        return elapsed >= self._recovery_seconds
