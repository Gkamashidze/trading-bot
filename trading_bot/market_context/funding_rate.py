"""Binance Futures funding rate provider.

Funding settles every 8 hours (00:00, 08:00, 16:00 UTC).
Cached for 8 hours. Uses the public premiumIndex endpoint — no API key needed.

Interpretation:
  positive funding → longs pay shorts → market is overleveraged long → mild bearish
  negative funding → shorts pay longs → market is overleveraged short → uncertain/cautious
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
_SETTLEMENT_HOURS = (0, 8, 16)  # UTC hours when Binance settles funding


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
        """Return current funding rate as a float (e.g. 0.0001 = 0.01%).
        Cache expires at the next 8-hour settlement window (00:00, 08:00, 16:00 UTC)
        so the rate is always fresh when a new funding period begins.
        """
        now = datetime.now(UTC)
        if self._expires_at and now < self._expires_at and self._rate is not None:
            return self._rate

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(_URL, params={"symbol": symbol})
                resp.raise_for_status()
                data = resp.json()
                self._rate = float(data["lastFundingRate"])
                self._expires_at = _next_settlement(now)
                log.info("funding_rate_fetched", symbol=symbol, rate=self._rate)
        except Exception as e:
            log.error("funding_rate_fetch_failed", symbol=symbol, error=str(e))
            await _send_context_alert("Funding Rate API failure", str(e))

        return self._rate


async def _send_context_alert(title: str, detail: str) -> None:
    from trading_bot.alerts.telegram import AlertLevel, TelegramAlerter

    alerter = TelegramAlerter.from_env_optional()
    if alerter:
        await alerter.send(AlertLevel.ERROR, title, detail=detail[:300])
