"""Fear & Greed Index provider — Alternative.me public API.

Updates once daily. Cached for 23 hours to align with daily publish cadence.
No API key required.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_URL = "https://api.alternative.me/fng/?limit=1&format=json"
_TTL = timedelta(hours=23)  # published once per day; no need to refetch hourly


class FearGreedProvider:
    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout
        self._value: int | None = None
        self._label: str | None = None
        self._expires_at: datetime | None = None

    async def fetch(self) -> tuple[int | None, str | None]:
        """Return (value 0-100, label). Returns cached value within TTL."""
        now = datetime.now(UTC)
        if self._expires_at and now < self._expires_at and self._value is not None:
            return self._value, self._label

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(_URL)
                resp.raise_for_status()
                data = resp.json()["data"][0]
                self._value = int(data["value"])
                self._label = data["value_classification"]
                self._expires_at = now + _TTL
                log.info("fear_greed_fetched", value=self._value, label=self._label)
        except Exception as e:
            log.error("fear_greed_fetch_failed", error=str(e))
            await _send_context_alert("Fear & Greed API failure", str(e))

        return self._value, self._label


async def _send_context_alert(title: str, detail: str) -> None:
    from trading_bot.alerts.telegram import AlertLevel, TelegramAlerter

    alerter = TelegramAlerter.from_env_optional()
    if alerter:
        await alerter.send(AlertLevel.ERROR, title, detail=detail[:300])
