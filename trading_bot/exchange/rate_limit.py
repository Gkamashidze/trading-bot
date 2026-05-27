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
import json
import re
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    rate_limited_until_ms: int = 0
    last_weight_used: int = 0
    last_weight_updated_at: float = 0.0
    last_ban_alert_at: float = 0.0
    last_rate_limit_alert_at: float = 0.0
    last_weight_alert_at: float = 0.0
    last_weight_alert_level: str = ""  # "", "warning", "critical"


_circuits: dict[str, CircuitState] = {}
_request_locks: dict[str, asyncio.Lock] = {}
_state_path: Path | None = None


def configure_state_store(path: Path | None) -> None:
    """Load circuit state from persistent storage and enable later saves.

    Railway mounts ``/data`` across deploys. Persisting the exchange circuit
    there prevents a restart from immediately probing an IP that is still
    banned or inside a Retry-After window.
    """
    global _state_path
    _state_path = path
    if path is None or not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for exchange_id, state in payload.items():
            if not isinstance(exchange_id, str) or not isinstance(state, dict):
                continue
            c = get_circuit(exchange_id)
            c.banned_until_ms = int(state.get("banned_until_ms", 0))
            c.rate_limited_until_ms = int(state.get("rate_limited_until_ms", 0))
            c.last_ban_alert_at = float(state.get("last_ban_alert_at", 0.0))
            c.last_rate_limit_alert_at = float(state.get("last_rate_limit_alert_at", 0.0))
        log.info("exchange_circuit_state_loaded", path=str(path))
    except Exception as exc:
        log.warning("exchange_circuit_state_load_failed", path=str(path), error=str(exc))


def _persist_state() -> None:
    if _state_path is None:
        return
    try:
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            exchange_id: {
                "banned_until_ms": state.banned_until_ms,
                "rate_limited_until_ms": state.rate_limited_until_ms,
                "last_ban_alert_at": state.last_ban_alert_at,
                "last_rate_limit_alert_at": state.last_rate_limit_alert_at,
            }
            for exchange_id, state in _circuits.items()
        }
        tmp_path = _state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(_state_path)
    except Exception as exc:
        log.warning("exchange_circuit_state_save_failed", path=str(_state_path), error=str(exc))


def get_circuit(exchange_id: str) -> CircuitState:
    return _circuits.setdefault(exchange_id, CircuitState())


@asynccontextmanager
async def request_slot(exchange_id: str) -> AsyncGenerator[None, None]:
    """Serialize REST requests so a detected ban stops queued calls."""
    lock = _request_locks.setdefault(exchange_id, asyncio.Lock())
    async with lock:
        yield


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
    seconds_remaining = max(0, (c.banned_until_ms - int(time.time() * 1000)) // 1000)
    EXCHANGE_CIRCUIT_OPEN.labels(exchange=exchange_id).set(1)
    _persist_state()
    log.error(
        "exchange_circuit_tripped",
        exchange=exchange_id,
        banned_until_ms=c.banned_until_ms,
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
        _persist_state()
        log.info("exchange_circuit_reset", exchange=exchange_id)
        return 0
    return remaining_ms // 1000


def mark_rate_limited(exchange_id: str, retry_after_seconds: float) -> None:
    """Stop further REST requests until Binance's Retry-After has elapsed."""
    c = get_circuit(exchange_id)
    until_ms = int((time.time() + max(retry_after_seconds, 1.0)) * 1000)
    c.rate_limited_until_ms = max(c.rate_limited_until_ms, until_ms)
    _persist_state()
    log.warning(
        "exchange_rate_limit_blocked",
        exchange=exchange_id,
        retry_after_seconds=retry_after_seconds,
        rate_limited_until_ms=c.rate_limited_until_ms,
    )


def check_rate_limit_cooldown(exchange_id: str) -> int:
    """Return seconds remaining in a Retry-After cooldown, or zero."""
    c = get_circuit(exchange_id)
    remaining_ms = c.rate_limited_until_ms - int(time.time() * 1000)
    if remaining_ms <= 0:
        if c.rate_limited_until_ms:
            c.rate_limited_until_ms = 0
            _persist_state()
        return 0
    return max(1, remaining_ms // 1000)


def parse_retry_after_seconds(headers: Any, default: float = 60.0) -> float:
    """Return a safe Retry-After duration from response headers."""
    if not headers:
        return default
    raw = headers.get("Retry-After") or headers.get("retry-after")
    try:
        return max(float(raw), 1.0) if raw is not None else default
    except (TypeError, ValueError):
        return default


def should_alert_ban(exchange_id: str, dedup_window_s: int = 3600) -> bool:
    """Return True if we should send a Telegram alert about this ban.

    Dedups within a 1-hour window so repeated REST calls during a long ban
    don't spam the operator.
    """
    c = get_circuit(exchange_id)
    now = time.time()
    if now - c.last_ban_alert_at >= dedup_window_s:
        c.last_ban_alert_at = now
        _persist_state()
        return True
    return False


def should_alert_rate_limit(exchange_id: str, dedup_window_s: int = 3600) -> bool:
    """Deduplicate direct 429/Retry-After alerts."""
    c = get_circuit(exchange_id)
    now = time.time()
    if now - c.last_rate_limit_alert_at >= dedup_window_s:
        c.last_rate_limit_alert_at = now
        _persist_state()
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
