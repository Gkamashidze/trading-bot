"""Binance Futures funding rate provider.

Funding settles every 8 hours (00:00, 08:00, 16:00 UTC).
Cached for 8 hours. Uses the public premiumIndex endpoint — no API key needed.

Interpretation:
  positive funding → longs pay shorts → market is overleveraged long → mild bearish
  negative funding → shorts pay longs → market is overleveraged short → mild bullish
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
_TTL = timedelta(hours=8)


class FundingRateProvider:
    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._rate: float | None = None
        self._expires_at: datetime | None = None

    async def fetch(self, symbol: str = "BTCUSDT") -> float | None:
        """Return current funding rate as a float (e.g. 0.0001 = 0.01%).
        Returns cached value within TTL.
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
                self._expires_at = now + _TTL
                log.info("funding_rate_fetched", symbol=symbol, rate=self._rate)
        except Exception as e:
            log.warning("funding_rate_fetch_failed", symbol=symbol, error=str(e))

        return self._rate
