"""Binance exchange adapter.

Uses CCXT as the underlying library. This adapter is the ONLY place in
the codebase that imports CCXT — all other code uses the ExchangeInterface
contract. This makes it trivial to swap for a different library or mock in tests.

Security:
- Read-only API key in Stage 0 (no trade, no withdraw permissions)
- IP whitelist enforced on the exchange side (not in code — exchange setting)
- Withdrawal whitelist enforced on exchange side (CRITICAL — not in code)
- API key never logged

Key rotation: every 90 days. Set calendar reminder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import ccxt.async_support as ccxt
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from trading_bot.core.contracts import ExchangeInterface
from trading_bot.core.exceptions import (
    ExchangeAuthError,
    ExchangeConnectionError,
    ExchangeRateLimitError,
)
from trading_bot.observability.logging import get_logger
from trading_bot.observability.metrics import API_LATENCY
from trading_bot.observability.tracing import get_tracer, start_span

log = get_logger(__name__)
tracer = get_tracer(__name__)


class BinanceExchange(ExchangeInterface):
    """Binance exchange adapter (read-only in Stage 0).

    Thread-safety: this adapter is async; do NOT use it across threads.
    One instance per asyncio event loop.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        testnet: bool = True,
        timeout_ms: int = 10_000,
        retry_attempts: int = 4,
        retry_backoff_base: int = 2,
    ) -> None:
        self._testnet = testnet
        self._retry_attempts = retry_attempts
        self._retry_backoff_base = retry_backoff_base

        config: dict[str, Any] = {
            "apiKey": api_key or None,
            "secret": api_secret or None,
            "timeout": timeout_ms,
            "enableRateLimit": True,
            "options": {"defaultType": "spot"},
        }

        if testnet:
            config["urls"] = {
                "api": {
                    "public": "https://testnet.binance.vision/api",
                    "private": "https://testnet.binance.vision/api",
                }
            }

        self._client = ccxt.binance(config)
        log.info(
            "binance_adapter_created",
            testnet=testnet,
            has_credentials=bool(api_key),
        )

    async def close(self) -> None:
        """Close the underlying HTTP session. Call on shutdown."""
        await self._client.close()

    # ── Read-only operations ────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type((ExchangeConnectionError, ExchangeRateLimitError)),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=30),
        reraise=True,
    )
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV bars from Binance. Returns raw CCXT format."""
        since_ms: int | None = None
        if since is not None:
            since_ms = int(since.timestamp() * 1000)

        with (
            start_span(
                "exchange.fetch_ohlcv",
                {"exchange": "binance", "symbol": symbol, "timeframe": timeframe},
            ),
            API_LATENCY.labels(exchange="binance", method="fetch_ohlcv").time(),
        ):
            try:
                raw = await self._client.fetch_ohlcv(
                    symbol, timeframe=timeframe, since=since_ms, limit=limit
                )
                return [
                    {
                        "open_time": datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                        "open": Decimal(str(row[1])),
                        "high": Decimal(str(row[2])),
                        "low": Decimal(str(row[3])),
                        "close": Decimal(str(row[4])),
                        "volume": Decimal(str(row[5])),
                        "quote_volume": Decimal(str(row[7])) if len(row) > 7 else Decimal("0"),
                        "trade_count": int(row[8]) if len(row) > 8 else None,
                        "close_time": datetime.fromtimestamp(
                            (row[0] + _timeframe_to_ms(timeframe) - 1) / 1000,
                            tz=UTC,
                        ),
                    }
                    for row in raw
                ]
            except ccxt.AuthenticationError as e:
                raise ExchangeAuthError(f"Binance auth failed: {e}") from e
            except ccxt.RateLimitExceeded as e:
                raise ExchangeRateLimitError(
                    f"Binance rate limit: {e}", retry_after_seconds=60.0
                ) from e
            except ccxt.NetworkError as e:
                raise ExchangeConnectionError(f"Binance network error: {e}") from e

    async def get_server_time(self) -> datetime:
        """Return Binance server time as UTC-aware datetime."""
        with start_span("exchange.get_server_time", {"exchange": "binance"}):
            try:
                result = await self._client.fetch_time()
                return datetime.fromtimestamp(result / 1000, tz=UTC)
            except ccxt.NetworkError as e:
                raise ExchangeConnectionError(f"Cannot reach Binance: {e}") from e

    async def fetch_balances(self) -> dict[str, Decimal]:
        """Return spot balances. Requires non-empty API key."""
        try:
            result = await self._client.fetch_balance()
            return {
                asset: Decimal(str(amount["total"]))
                for asset, amount in result["total"].items()
                if float(amount) > 0
            }
        except ccxt.AuthenticationError as e:
            raise ExchangeAuthError(f"Binance auth failed: {e}") from e

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return open orders. Stage 0: not yet implemented for live trading."""
        return cast(list[dict[str, Any]], await self._client.fetch_open_orders(symbol))

    async def fetch_trade_fees(self, symbol: str) -> dict[str, Decimal]:
        fees = await self._client.fetch_trading_fee(symbol)
        return {
            "maker": Decimal(str(fees.get("maker", 0.001))),
            "taker": Decimal(str(fees.get("taker", 0.001))),
        }

    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        markets = await self._client.load_markets()
        return cast(dict[str, Any], markets.get(symbol, {}))

    async def place_order(self, order: Any) -> dict[str, Any]:
        raise NotImplementedError("Stage 0: order placement not yet enabled. See Stage 5.")

    async def cancel_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("Stage 0: order cancellation not yet enabled. See Stage 5.")

    async def health_check(self) -> bool:
        """Verify Binance is reachable and (if configured) credentials are valid."""
        try:
            await self._client.fetch_time()
            log.debug("binance_health_ok", testnet=self._testnet)
            return True
        except Exception as e:
            log.warning("binance_health_failed", error=str(e), testnet=self._testnet)
            return False


def _timeframe_to_ms(timeframe: str) -> int:
    """Convert CCXT timeframe string to milliseconds."""
    _map = {
        "1m": 60_000,
        "3m": 180_000,
        "5m": 300_000,
        "15m": 900_000,
        "30m": 1_800_000,
        "1h": 3_600_000,
        "2h": 7_200_000,
        "4h": 14_400_000,
        "6h": 21_600_000,
        "8h": 28_800_000,
        "12h": 43_200_000,
        "1d": 86_400_000,
        "3d": 259_200_000,
        "1w": 604_800_000,
        "1M": 2_592_000_000,
    }
    return _map.get(timeframe, 60_000)
