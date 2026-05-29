"""Binance Futures funding rate provider.

Funding settles every 8 hours (00:00, 08:00, 16:00 UTC).
Cached for 8 hours on success, 1 hour on failure, full ban window on ban.
Uses the public premiumIndex endpoint — no API key needed.

Interpretation:
  positive funding → longs pay shorts → market is overleveraged long → mild bearish
  negative funding → shorts pay longs → market is overleveraged short → uncertain/cautious

Rate-limit safety:
  - Reuses the shared Binance circuit breaker (exchange.rate_limit) so a 418
    ban triggered elsewhere also pauses these calls.
  - 418 response trips the circuit and caches None until the ban expires.
  - Generic failures cached for 1h (no retry every poll).
  - Alert level: WARNING (not ERROR) — funding rate is non-critical.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from trading_bot.exchange.rate_limit import (
    check_circuit,
    check_rate_limit_cooldown,
    mark_rate_limited,
    parse_ban_timestamp_ms,
    parse_retry_after_seconds,
    request_slot,
    should_alert_rate_limit,
    trip_circuit,
)
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
_SETTLEMENT_HOURS = (0, 8, 16)  # UTC hours when Binance settles funding
_TTL_FAILURE = timedelta(hours=1)  # retry generic failures after 1h, not every poll
_STATE_FILE = "funding_rate_state.json"


@dataclass
class _FundingCacheEntry:
    rate: float | None
    expires_at: datetime


_cache: dict[str, _FundingCacheEntry] = {}
_lock = asyncio.Lock()
_state_loaded = False
_state_path: Path | None = None
_ban_alert_silenced_until_ms = 0


def _next_settlement(now: datetime) -> datetime:
    """Return the next 8-hour funding settlement time after `now` (UTC)."""
    for hour in _SETTLEMENT_HOURS:
        candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if candidate > now:
            return candidate
    # All three windows are in the past for today — next is 00:00 tomorrow
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)


class FundingRateProvider:
    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._rate: float | None = None
        self._expires_at: datetime | None = None

    async def fetch(self, symbol: str = "BTCUSDT") -> float | None:
        """Return current funding rate as a float (e.g. 0.0001 = 0.01%)."""
        now = datetime.now(UTC)
        _ensure_state_loaded()

        async with _lock:
            return await self._fetch_locked(symbol=symbol, now=now)

    async def _fetch_locked(self, *, symbol: str, now: datetime) -> float | None:
        # Cache still warm? Return without touching the network. Keep the
        # instance fields in sync for tests and legacy callers that inspect them.
        cached = _cache.get(symbol)
        if cached and now < cached.expires_at:
            self._rate = cached.rate
            self._expires_at = cached.expires_at
            return cached.rate
        if self._expires_at and now < self._expires_at:
            _cache[symbol] = _FundingCacheEntry(rate=self._rate, expires_at=self._expires_at)
            return self._rate

        # Skip if Binance has banned our IP (shared circuit with REST adapter)
        ban_seconds = check_circuit("binance")
        if ban_seconds > 0:
            expires_at = now + timedelta(seconds=ban_seconds + 1)
            self._set_cache(symbol, self._rate, expires_at)
            log.warning(
                "funding_rate_skipped_ban_active",
                symbol=symbol,
                ban_seconds_remaining=ban_seconds,
            )
            return self._rate
        cooldown_seconds = check_rate_limit_cooldown("binance")
        if cooldown_seconds > 0:
            self._set_cache(symbol, self._rate, now + timedelta(seconds=cooldown_seconds + 1))
            log.warning(
                "funding_rate_skipped_rate_limit_cooldown",
                symbol=symbol,
                retry_after_seconds=cooldown_seconds,
            )
            return self._rate

        try:
            async with request_slot("binance"):
                ban_seconds = check_circuit("binance")
                cooldown_seconds = check_rate_limit_cooldown("binance")
                if ban_seconds > 0 or cooldown_seconds > 0:
                    wait_seconds = max(ban_seconds, cooldown_seconds)
                    self._set_cache(symbol, self._rate, now + timedelta(seconds=wait_seconds + 1))
                    return self._rate
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.get(_URL, params={"symbol": symbol})
                    # Detect IP ban before raise_for_status wraps it generically.
                    if resp.status_code in (418, 429):
                        banned_until_ms = parse_ban_timestamp_ms(resp.text)
                        if banned_until_ms is not None:
                            trip_circuit("binance", banned_until_ms)
                            expires_at = datetime.fromtimestamp(banned_until_ms / 1000, tz=UTC)
                            self._set_cache(symbol, self._rate, expires_at)
                            if _should_alert_funding_ban(banned_until_ms):
                                await _send_context_alert(
                                    "funding_rate_banned",
                                    "Binance IP banned via Funding Rate endpoint - "
                                    "caching None until ban expires",
                                )
                            return self._rate
                    if resp.status_code == 429:
                        retry_after = parse_retry_after_seconds(resp.headers)
                        mark_rate_limited("binance", retry_after)
                        self._set_cache(symbol, self._rate, now + timedelta(seconds=retry_after))
                        if should_alert_rate_limit("binance"):
                            await _send_context_alert(
                                "funding_rate_rate_limited",
                                f"Binance requested Retry-After={retry_after:.0f}s",
                            )
                        return self._rate
                    resp.raise_for_status()
                    data = resp.json()
                    self._set_cache(symbol, float(data["lastFundingRate"]), _next_settlement(now))
                    log.info("funding_rate_fetched", symbol=symbol, rate=self._rate)
        except Exception as e:
            # Cache the failure for 1h so we don't retry every market-context poll
            self._set_cache(symbol, self._rate, now + _TTL_FAILURE)
            log.warning("funding_rate_fetch_failed", symbol=symbol, error=str(e))
            await _send_context_alert("funding_rate_unavailable", str(e))

        return self._rate

    def _set_cache(self, symbol: str, rate: float | None, expires_at: datetime) -> None:
        self._rate = rate
        self._expires_at = expires_at
        _cache[symbol] = _FundingCacheEntry(rate=rate, expires_at=expires_at)
        _persist_state()


def _state_store_path() -> Path | None:
    try:
        from trading_bot.config import get_settings

        return Path(get_settings().storage.raw_path).parent / _STATE_FILE
    except Exception as exc:
        log.warning("funding_rate_state_path_unavailable", error=str(exc))
        return None


def _ensure_state_loaded() -> None:
    global _ban_alert_silenced_until_ms, _state_loaded, _state_path
    if _state_loaded:
        return
    _state_loaded = True
    _state_path = _state_store_path()
    if _state_path is None or not _state_path.exists():
        return
    try:
        payload = json.loads(_state_path.read_text(encoding="utf-8"))
        _ban_alert_silenced_until_ms = int(payload.get("ban_alert_silenced_until_ms", 0))
        for symbol, raw in payload.get("cache", {}).items():
            if not isinstance(symbol, str) or not isinstance(raw, dict):
                continue
            expires_at_raw = raw.get("expires_at")
            if not isinstance(expires_at_raw, str):
                continue
            expires_at = datetime.fromisoformat(expires_at_raw)
            if expires_at.tzinfo is None:
                continue
            if datetime.now(UTC) < expires_at:
                rate = raw.get("rate")
                _cache[symbol] = _FundingCacheEntry(
                    rate=float(rate) if rate is not None else None,
                    expires_at=expires_at,
                )
        log.info(
            "funding_rate_state_loaded",
            path=str(_state_path),
            cached_symbols=len(_cache),
        )
    except Exception as exc:
        log.warning("funding_rate_state_load_failed", path=str(_state_path), error=str(exc))


def _persist_state() -> None:
    if _state_path is None:
        return
    try:
        _state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ban_alert_silenced_until_ms": _ban_alert_silenced_until_ms,
            "cache": {
                symbol: {
                    "rate": entry.rate,
                    "expires_at": entry.expires_at.isoformat(),
                }
                for symbol, entry in _cache.items()
            },
        }
        tmp_path = _state_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp_path.replace(_state_path)
    except Exception as exc:
        log.warning("funding_rate_state_save_failed", path=str(_state_path), error=str(exc))


def _should_alert_funding_ban(banned_until_ms: int) -> bool:
    global _ban_alert_silenced_until_ms
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    if now_ms < _ban_alert_silenced_until_ms:
        return False
    _ban_alert_silenced_until_ms = max(banned_until_ms, now_ms + 60_000)
    _persist_state()
    return True


def _reset_state_for_tests() -> None:
    global _ban_alert_silenced_until_ms, _state_loaded, _state_path
    _cache.clear()
    _ban_alert_silenced_until_ms = 0
    _state_loaded = True
    _state_path = None


async def _send_context_alert(title: str, detail: str) -> None:
    from trading_bot.alerts.telegram import AlertLevel, TelegramAlerter

    alerter = TelegramAlerter.from_env_optional()
    if alerter:
        await alerter.send(AlertLevel.WARNING, title, detail=detail[:300])
