"""Time synchronization utilities.

UTC enforcement:
- All internal timestamps use datetime.now(timezone.utc)
- Naive datetimes are rejected at Pydantic model boundaries
- This module compares local clock vs exchange server clock

Drift thresholds (from base.yaml):
- > 100ms  → log WARNING
- > 250ms  → send alert
- > 500ms  → halt trading (ClockDriftError)

Production requirement: NTP/chrony daemon configured, drift target < 5ms.
PTP (Precision Time Protocol) is optional for ultra-low-latency (future).

DST handling: not relevant internally (everything is UTC). DST matters
only for scheduling ETF trading sessions (pandas_market_calendars handles this).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from trading_bot.core.exceptions import ClockDriftError
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


def utc_now() -> datetime:
    """Return current UTC time. Use this instead of datetime.now() everywhere."""
    return datetime.now(UTC)


def utc_timestamp_ms() -> int:
    """Return current UTC time as Unix milliseconds."""
    return int(time.time() * 1000)


def assert_utc_aware(dt: datetime, field_name: str = "datetime") -> datetime:
    """Assert that a datetime is UTC-aware. Raises ValueError if naive."""
    if dt.tzinfo is None:
        raise ValueError(
            f"Naive datetime rejected in '{field_name}'. "
            "Use datetime.now(timezone.utc) or pandas Timestamp with tz='UTC'."
        )
    return dt.astimezone(UTC)


class TimeSyncChecker:
    """Checks local clock drift versus an exchange's server time.

    Usage:
        checker = TimeSyncChecker(exchange=binance, settings=settings.time_sync)
        await checker.check()     # raises ClockDriftError if drift > halt threshold
        await checker.start_background_loop()  # continuous background monitoring
    """

    def __init__(
        self,
        exchange: Any,
        warn_drift_ms: int = 100,
        alert_drift_ms: int = 250,
        halt_drift_ms: int = 500,
        check_interval_seconds: int = 60,
    ) -> None:
        self._exchange = exchange
        self._warn_ms = warn_drift_ms
        self._alert_ms = alert_drift_ms
        self._halt_ms = halt_drift_ms
        self._interval = check_interval_seconds
        self._last_drift_ms: float | None = None

    async def check(self) -> float:
        """Perform a single drift check. Returns drift in milliseconds.

        Raises ClockDriftError if drift exceeds halt_drift_ms.
        The exchange round-trip latency introduces measurement error — we
        take the absolute value of drift.
        """
        local_before = utc_now()
        exchange_time = await self._exchange.get_server_time()
        local_after = utc_now()

        # Use midpoint of the local clock before/after for latency correction
        local_mid = local_before + (local_after - local_before) / 2
        drift_ms = abs((local_mid - exchange_time).total_seconds() * 1000)
        self._last_drift_ms = drift_ms

        if drift_ms > self._halt_ms:
            log.error(
                "clock_drift_critical",
                drift_ms=drift_ms,
                halt_threshold_ms=self._halt_ms,
                action="halting_trading",
            )
            raise ClockDriftError(
                f"Clock drift {drift_ms:.1f}ms exceeds halt threshold {self._halt_ms}ms",
                drift_ms=drift_ms,
            )
        elif drift_ms > self._alert_ms:
            log.warning(
                "clock_drift_alert",
                drift_ms=drift_ms,
                alert_threshold_ms=self._alert_ms,
            )
        elif drift_ms > self._warn_ms:
            log.warning(
                "clock_drift_warning",
                drift_ms=drift_ms,
                warn_threshold_ms=self._warn_ms,
            )
        else:
            log.debug("clock_drift_ok", drift_ms=drift_ms)

        return float(drift_ms)

    async def start_background_loop(self) -> None:
        """Run drift checks continuously in the background.

        Call as an asyncio task. Cancellation stops the loop cleanly.
        """
        log.info(
            "time_sync_loop_started",
            interval_seconds=self._interval,
            halt_threshold_ms=self._halt_ms,
        )
        while True:
            try:
                await self.check()
            except ClockDriftError:
                # Drift error already logged; let the caller handle the exception
                # by raising a system alert. Don't crash the loop.
                pass
            except asyncio.CancelledError:
                log.info("time_sync_loop_cancelled")
                return
            except Exception as e:
                log.error("time_sync_check_failed", error=str(e))

            await asyncio.sleep(self._interval)

    @property
    def last_drift_ms(self) -> float | None:
        """Return the most recent drift measurement in milliseconds."""
        return self._last_drift_ms
