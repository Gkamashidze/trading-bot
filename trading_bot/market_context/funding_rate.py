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

from datetime import UTC, datetime, timedelta

import httpx

from trading_bot.exchange.rate_limit import (
    check_circuit,
    parse_ban_timestamp_ms,
    should_alert_ban,
    trip_circuit,
)
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
_SETTLEMENT_HOURS = (0, 8, 16)  # UTC hours when Binance settles funding
_TTL_FAILURE = timedelta(hours=1)  # retry generic failures after 1h, not every poll


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

        # Cache still warm? Return without touching the network.
        if self._expires_at and now < self._expires_at:
            return self._rate

        # Skip if Binance has banned our IP (shared circuit with REST adapter)
        ban_seconds = check_circuit("binance")
        if ban_seconds > 0:
            self._expires_at = now + timedelta(seconds=ban_seconds + 1)
            if should_alert_ban("binance"):
                await _send_context_alert(
                    "funding_rate_skipped_ban_active",
                    f"Binance ban active — {ban_seconds // 60}min remaining",
                )
            return self._rate

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(_URL, params={"symbol": symbol})
                # Detect IP ban *before* raise_for_status wraps it generically
                if resp.status_code in (418, 429):
                    banned_until_ms = parse_ban_timestamp_ms(resp.text)
                    if banned_until_ms is not None:
                        trip_circuit("binance", banned_until_ms)
                        self._expires_at = datetime.fromtimestamp(banned_until_ms / 1000, tz=UTC)
                        if should_alert_ban("binance"):
                            await _send_context_alert(
                                "funding_rate_banned",
                                "Binance IP banned via Funding Rate endpoint — "
                                "caching None until ban expires",
                            )
                        return self._rate
                resp.raise_for_status()
                data = resp.json()
                self._rate = float(data["lastFundingRate"])
                self._expires_at = _next_settlement(now)
                log.info("funding_rate_fetched", symbol=symbol, rate=self._rate)
        except Exception as e:
            # Cache the failure for 1h so we don't retry every market-context poll
            self._expires_at = now + _TTL_FAILURE
            log.warning("funding_rate_fetch_failed", symbol=symbol, error=str(e))
            await _send_context_alert("funding_rate_unavailable", str(e))

        return self._rate


async def _send_context_alert(title: str, detail: str) -> None:
    from trading_bot.alerts.telegram import AlertLevel, TelegramAlerter

    alerter = TelegramAlerter.from_env_optional()
    if alerter:
        await alerter.send(AlertLevel.WARNING, title, detail=detail[:300])
