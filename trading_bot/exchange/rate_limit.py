"""Exchange rate limit awareness + IP ban circuit breaker.

Prevents repeated REST calls when:
  1. Binance has banned our IP (418 / -1003) — wait until banned_until_ms.
  2. We are approaching our weight quota — back off preemptively.

Pattern:
    if not _can_proceed():       # check circuit
        raise ExchangeBannedError(...)
    raw = await client.fetch_ohlcv(...)
    _record_response_headers(client.last_response_headers)
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from trading_bot.observability.logging import get_logger
from trading_bot.observability.metrics import (
    EXCHANGE_CIRCUIT_OPEN,
    EXCHANGE_RATE_LIMIT_WEIGHT,
    EXCHANGE_RATE_LIMIT_WEIGHT_PCT,
)

log = get_logger(__name__)


# Binance spot weight limit per minute (default — overridden by /api/v3/exchangeInfo)
_SPOT_WEIGHT_LIMIT_PER_MIN = 6000
_SOFT_LIMIT_RATIO = 0.80  # back off at 80% of the limit
_WARNING_RATIO = 0.70  # Telegram WARNING when we cross 70%
_CRITICAL_RATIO = 0.90  # Telegram CRITICAL when we cross 90%
_BAN_REGEX = re.compile(r"banned until (\d+)", re.IGNORECASE)


@dataclass
class CircuitState:
    """Process-wide circuit state for a single exchange."""

    banned_until_ms: int = 0
    last_weight_used: int = 0
    last_weight_updated_at: float = 0.0
    last_ban_alert_at: float = 0.0
    last_weight_alert_at: float = 0.0
    last_weight_alert_level: str = ""  # "", "warning", "critical"


_circuits: dict[str, CircuitState] = {}


def get_circuit(exchange_id: str) -> CircuitState:
    return _circuits.setdefault(exchange_id, CircuitState())


def parse_ban_timestamp_ms(error_text: str) -> int | None:
    """Extract banned_until_ms from a Binance -1003 / 418 error message."""
    m = _BAN_REGEX.search(error_text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def trip_circuit(exchange_id: str, banned_until_ms: int) -> None:
    """Open the circuit until banned_until_ms. Called when 418/-1003 is detected."""
    c = get_circuit(exchange_id)
    c.banned_until_ms = max(c.banned_until_ms, banned_until_ms)
    seconds_remaining = max(0, (banned_until_ms - int(time.time() * 1000)) // 1000)
    EXCHANGE_CIRCUIT_OPEN.labels(exchange=exchange_id).set(1)
    log.error(
        "exchange_circuit_tripped",
        exchange=exchange_id,
        banned_until_ms=banned_until_ms,
        seconds_remaining=seconds_remaining,
    )


def check_circuit(exchange_id: str) -> int:
    """Return seconds remaining on the ban, or 0 if circuit is closed."""
    c = get_circuit(exchange_id)
    if c.banned_until_ms == 0:
        return 0
    now_ms = int(time.time() * 1000)
    remaining_ms = c.banned_until_ms - now_ms
    if remaining_ms <= 0:
        # Ban expired — reset
        c.banned_until_ms = 0
        EXCHANGE_CIRCUIT_OPEN.labels(exchange=exchange_id).set(0)
        log.info("exchange_circuit_reset", exchange=exchange_id)
        return 0
    return remaining_ms // 1000


def should_alert_ban(exchange_id: str, dedup_window_s: int = 3600) -> bool:
    """Return True if we should send a Telegram alert about this ban.

    Dedups within a 1-hour window so repeated REST calls during a long ban
    don't spam the operator.
    """
    c = get_circuit(exchange_id)
    now = time.time()
    if now - c.last_ban_alert_at >= dedup_window_s:
        c.last_ban_alert_at = now
        return True
    return False


def record_weight(exchange_id: str, weight: int) -> None:
    """Record the most recent X-MBX-USED-WEIGHT-1M header value.

    Emits Prometheus gauges and a Telegram alert when crossing 70% / 90% thresholds
    (deduped: at most one alert per level transition per 5 minutes).
    """
    c = get_circuit(exchange_id)
    c.last_weight_used = weight
    c.last_weight_updated_at = time.time()

    ratio = weight / _SPOT_WEIGHT_LIMIT_PER_MIN
    EXCHANGE_RATE_LIMIT_WEIGHT.labels(exchange=exchange_id).set(weight)
    EXCHANGE_RATE_LIMIT_WEIGHT_PCT.labels(exchange=exchange_id).set(ratio)

    new_level = ""
    if ratio >= _CRITICAL_RATIO:
        new_level = "critical"
    elif ratio >= _WARNING_RATIO:
        new_level = "warning"

    # Edge-triggered alert: only fire when we cross *into* a higher level,
    # and not more than once per 5 minutes.
    if new_level and new_level != c.last_weight_alert_level:
        now = time.time()
        if now - c.last_weight_alert_at >= 300:
            c.last_weight_alert_at = now
            c.last_weight_alert_level = new_level
            _fire_weight_alert(exchange_id, weight, ratio, new_level)
    elif not new_level and c.last_weight_alert_level:
        # Returned to safe range — reset so the next breach alerts again
        c.last_weight_alert_level = ""

    if ratio > _SOFT_LIMIT_RATIO:
        log.warning(
            "exchange_rate_limit_approaching",
            exchange=exchange_id,
            weight=weight,
            limit=_SPOT_WEIGHT_LIMIT_PER_MIN,
            ratio=f"{ratio:.2f}",
        )


def _fire_weight_alert(exchange_id: str, weight: int, ratio: float, level: str) -> None:
    """Send a fire-and-forget Telegram alert for a rate-limit threshold breach."""
    try:
        from trading_bot.alerts.telegram import AlertLevel, TelegramAlerter

        alerter = TelegramAlerter.from_env_optional()
        if alerter is None:
            return
        alert_level = AlertLevel.CRITICAL if level == "critical" else AlertLevel.WARNING

        detail = f"weight={weight}/{_SPOT_WEIGHT_LIMIT_PER_MIN} ({ratio:.1%}) — throttling REST"

        async def _send() -> None:
            await alerter.send(
                alert_level,
                f"exchange_rate_limit_{level}: {exchange_id}",
                detail=detail,
            )

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_send())  # noqa: RUF006
    except Exception as exc:
        log.debug("rate_limit_alert_fire_failed", error=str(exc))


def should_throttle(exchange_id: str) -> bool:
    """Return True if we should preemptively back off (≥ soft limit)."""
    c = get_circuit(exchange_id)
    return c.last_weight_used > _SOFT_LIMIT_RATIO * _SPOT_WEIGHT_LIMIT_PER_MIN


async def cooldown_if_needed(exchange_id: str, seconds: int = 60) -> None:
    """Sleep for `seconds` if we are above the soft rate limit."""
    if should_throttle(exchange_id):
        log.warning("exchange_rate_limit_cooldown", exchange=exchange_id, seconds=seconds)
        await asyncio.sleep(seconds)
