"""FRED macro data provider — Federal Reserve Economic Data.

Fetches:
  - FEDFUNDS: Effective Federal Funds Rate (monthly, %)
  - CPIAUCSL: CPI All Urban Consumers (monthly index level)
    → computes YoY % change from last 13 observations

API key: free registration at https://fred.stlouisfed.org/docs/api/api_key.html
Set via FRED_API_KEY environment variable.

Data updates monthly. Cached for 24 hours.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_BASE = "https://api.stlouisfed.org/fred/series/observations"
_TTL_SUCCESS = timedelta(hours=24)
_TTL_FAILURE = timedelta(hours=1)  # retry sooner after a transient API error


class MacroProvider:
    def __init__(self, api_key: str, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._timeout = timeout
        self._fed_rate: float | None = None
        self._cpi_yoy: float | None = None
        self._expires_at: datetime | None = None

    async def fetch(self) -> tuple[float | None, float | None]:
        """Return (fed_funds_rate %, cpi_yoy %). Cached for 24 hours."""
        now = datetime.now(UTC)
        if self._expires_at and now < self._expires_at:
            return self._fed_rate, self._cpi_yoy

        if not self._api_key:
            log.warning("macro_skipped", reason="FRED_API_KEY not set")
            return None, None

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            self._fed_rate = await self._fetch_fed_rate(client)
            self._cpi_yoy = await self._fetch_cpi_yoy(client)

        success = self._fed_rate is not None or self._cpi_yoy is not None
        self._expires_at = now + (_TTL_SUCCESS if success else _TTL_FAILURE)
        log.info("macro_fetched", fed_rate=self._fed_rate, cpi_yoy=self._cpi_yoy)
        return self._fed_rate, self._cpi_yoy

    async def _fetch_fed_rate(self, client: httpx.AsyncClient) -> float | None:
        try:
            resp = await client.get(
                _BASE,
                params={
                    "series_id": "FEDFUNDS",
                    "api_key": self._api_key,
                    "sort_order": "desc",
                    "limit": "1",
                    "file_type": "json",
                },
            )
            resp.raise_for_status()
            obs = resp.json()["observations"]
            if obs and obs[0]["value"] != ".":
                return float(obs[0]["value"])
        except Exception as e:
            log.warning("fred_fedfunds_failed", error=str(e))
            await _send_context_alert("FRED Fed Funds Rate მიუწვდომელია", str(e))
        return None

    async def _fetch_cpi_yoy(self, client: httpx.AsyncClient) -> float | None:
        try:
            resp = await client.get(
                _BASE,
                params={
                    "series_id": "CPIAUCSL",
                    "api_key": self._api_key,
                    "sort_order": "desc",
                    "limit": "13",
                    "file_type": "json",
                },
            )
            resp.raise_for_status()
            obs = [o for o in resp.json()["observations"] if o["value"] != "."]
            if len(obs) >= 13:
                latest = float(obs[0]["value"])
                year_ago = float(obs[12]["value"])
                return round((latest / year_ago - 1) * 100, 2)
        except Exception as e:
            log.warning("fred_cpi_failed", error=str(e))
            await _send_context_alert("FRED CPI მიუწვდომელია", str(e))
        return None


async def _send_context_alert(title: str, detail: str) -> None:
    from trading_bot.alerts.telegram import AlertLevel, TelegramAlerter

    alerter = TelegramAlerter.from_env_optional()
    if alerter:
        await alerter.send(AlertLevel.WARNING, title, detail=detail[:300])
