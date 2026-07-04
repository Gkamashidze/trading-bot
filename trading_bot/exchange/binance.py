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

import time
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
    ExchangeBannedError,
    ExchangeConnectionError,
    ExchangeRateLimitError,
    OrderRejectedError,
)
from trading_bot.core.models import OrderRequest, OrderType
from trading_bot.exchange.precision import (
    OrderPrecisionValidator,
    SymbolConstraints,
)
from trading_bot.exchange.rate_limit import (
    check_circuit,
    check_rate_limit_cooldown,
    cooldown_if_needed,
    mark_rate_limited,
    parse_ban_timestamp_ms,
    parse_retry_after_seconds,
    record_weight,
    request_slot,
    trip_circuit,
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
        self._validator = OrderPrecisionValidator()
        self._constraints_cache: dict[str, SymbolConstraints] = {}

        config: dict[str, Any] = {
            "apiKey": api_key or None,
            "secret": api_secret or None,
            "timeout": timeout_ms,
            "enableRateLimit": True,
            # Restrict metadata discovery to spot. The default CCXT Binance
            # configuration also loads futures and delivery market catalogs.
            "options": {
                "defaultType": "spot",
                "fetchMarkets": {"types": ["spot"]},
                # Pass base-asset amount for market BUYs (not quote quantity),
                # matching how the router sizes orders in base units.
                "createMarketBuyOrderRequiresPrice": False,
            },
        }

        self._client = ccxt.binance(config)
        if testnet:
            # Use CCXT's sandbox switch — it sets the correct spot-testnet URLs
            # (testnet.binance.vision/api/v3/...). A manual urls override misses
            # the version path and 404s on exchangeInfo/ticker/order endpoints.
            self._client.set_sandbox_mode(True)
        log.info(
            "binance_adapter_created",
            testnet=testnet,
            has_credentials=bool(api_key),
        )

    async def close(self) -> None:
        """Close the underlying HTTP session. Call on shutdown."""
        await self._client.close()

    def _assert_request_allowed(self) -> None:
        """Raise before touching Binance while a ban or Retry-After is active."""
        ban_seconds_remaining = check_circuit("binance")
        if ban_seconds_remaining > 0:
            raise ExchangeBannedError(
                f"Binance IP ban active — {ban_seconds_remaining}s remaining",
                banned_until_ms=int(time.time() * 1000) + ban_seconds_remaining * 1000,
            )
        cooldown_seconds = check_rate_limit_cooldown("binance")
        if cooldown_seconds > 0:
            raise ExchangeRateLimitError(
                f"Binance Retry-After active — {cooldown_seconds}s remaining",
                retry_after_seconds=float(cooldown_seconds),
            )

    def _handle_ccxt_error(self, exc: Exception) -> Exception:
        """Translate a CCXT error into the proper trading_bot exception.

        Trips the circuit if the error contains a 'banned until' marker.
        Returns the exception to raise (caller does `raise self._handle_ccxt_error(e)`).
        """
        msg = str(exc)
        banned_until_ms = parse_ban_timestamp_ms(msg)
        if banned_until_ms is not None:
            trip_circuit("binance", banned_until_ms)
            return ExchangeBannedError(
                f"Binance IP banned: {exc}",
                banned_until_ms=banned_until_ms,
            )
        if isinstance(exc, ccxt.DDoSProtection) and " 418 " in msg:
            retry_after = parse_retry_after_seconds(
                getattr(self._client, "last_response_headers", None)
            )
            banned_until_ms = int((time.time() + retry_after) * 1000)
            trip_circuit("binance", banned_until_ms)
            return ExchangeBannedError(
                f"Binance IP banned: {exc}",
                banned_until_ms=banned_until_ms,
            )
        if isinstance(exc, ccxt.AuthenticationError):
            return ExchangeAuthError(f"Binance auth failed: {exc}")
        if isinstance(exc, ccxt.RateLimitExceeded) or (
            isinstance(exc, ccxt.DDoSProtection) and " 429 " in msg
        ):
            retry_after = parse_retry_after_seconds(
                getattr(self._client, "last_response_headers", None)
            )
            mark_rate_limited("binance", retry_after)
            return ExchangeRateLimitError(
                f"Binance rate limit: {exc}", retry_after_seconds=retry_after
            )
        if isinstance(exc, ccxt.NetworkError):
            return ExchangeConnectionError(f"Binance network error: {exc}")
        return exc

    # ── Read-only operations ────────────────────────────────────────────────

    @retry(
        # Never retry 429: Binance requires clients to honor Retry-After.
        retry=retry_if_exception_type(ExchangeConnectionError),
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
        """Fetch spot OHLCV bars without CCXT's implicit market-catalog request."""

        since_ms: int | None = None
        if since is not None:
            since_ms = int(since.timestamp() * 1000)
        params: dict[str, Any] = {
            "symbol": symbol.replace("/", "").split(":")[0],
            "interval": timeframe,
            "limit": min(limit, 1000),
        }
        if since_ms is not None:
            params["startTime"] = since_ms

        async with request_slot("binance"):
            self._assert_request_allowed()
            await cooldown_if_needed("binance", seconds=60)
            self._assert_request_allowed()
            with (
                start_span(
                    "exchange.fetch_ohlcv",
                    {"exchange": "binance", "symbol": symbol, "timeframe": timeframe},
                ),
                API_LATENCY.labels(exchange="binance", method="fetch_ohlcv").time(),
            ):
                try:
                    raw = await self._client.public_get_klines(params)
                    self._record_rate_limit_headers()
                    return [
                        {
                            "open_time": datetime.fromtimestamp(row[0] / 1000, tz=UTC),
                            "open": Decimal(str(row[1])),
                            "high": Decimal(str(row[2])),
                            "low": Decimal(str(row[3])),
                            "close": Decimal(str(row[4])),
                            "volume": Decimal(str(row[5])),
                            "quote_volume": (
                                Decimal(str(row[7])) if len(row) > 7 else Decimal("0")
                            ),
                            "trade_count": int(row[8]) if len(row) > 8 else None,
                            "close_time": datetime.fromtimestamp(
                                (row[0] + _timeframe_to_ms(timeframe) - 1) / 1000,
                                tz=UTC,
                            ),
                        }
                        for row in raw
                    ]
                except Exception as e:
                    raise self._handle_ccxt_error(e) from e

    def _record_rate_limit_headers(self) -> None:
        """Parse X-MBX-USED-WEIGHT-1M from the last CCXT response."""
        try:
            headers = getattr(self._client, "last_response_headers", None)
            if not headers:
                return
            weight_str = headers.get("X-MBX-USED-WEIGHT-1M") or headers.get("x-mbx-used-weight-1m")
            if weight_str:
                record_weight("binance", int(weight_str))
        except Exception as exc:
            log.debug("rate_limit_header_parse_failed", error=str(exc))

    async def get_server_time(self) -> datetime:
        """Return Binance server time as UTC-aware datetime."""
        async with request_slot("binance"):
            self._assert_request_allowed()
            with start_span("exchange.get_server_time", {"exchange": "binance"}):
                try:
                    result = await self._client.fetch_time()
                    self._record_rate_limit_headers()
                    return datetime.fromtimestamp(result / 1000, tz=UTC)
                except Exception as e:
                    raise self._handle_ccxt_error(e) from e

    async def fetch_balances(self) -> dict[str, Decimal]:
        """Return spot balances. Requires non-empty API key."""
        async with request_slot("binance"):
            self._assert_request_allowed()
            try:
                result = await self._client.fetch_balance()
                self._record_rate_limit_headers()
                return {
                    asset: Decimal(str(amount["total"]))
                    for asset, amount in result["total"].items()
                    if float(amount) > 0
                }
            except Exception as e:
                raise self._handle_ccxt_error(e) from e

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return open orders. Stage 0: not yet implemented for live trading."""
        async with request_slot("binance"):
            self._assert_request_allowed()
            try:
                result = cast(list[dict[str, Any]], await self._client.fetch_open_orders(symbol))
                self._record_rate_limit_headers()
                return result
            except Exception as e:
                raise self._handle_ccxt_error(e) from e

    async def fetch_trade_fees(self, symbol: str) -> dict[str, Decimal]:
        async with request_slot("binance"):
            self._assert_request_allowed()
            try:
                fees = await self._client.fetch_trading_fee(symbol)
                self._record_rate_limit_headers()
            except Exception as e:
                raise self._handle_ccxt_error(e) from e
        return {
            "maker": Decimal(str(fees.get("maker", 0.001))),
            "taker": Decimal(str(fees.get("taker", 0.001))),
        }

    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        async with request_slot("binance"):
            self._assert_request_allowed()
            try:
                markets = await self._client.load_markets()
                self._record_rate_limit_headers()
            except Exception as e:
                raise self._handle_ccxt_error(e) from e
        return cast(dict[str, Any], markets.get(symbol, {}))

    # ── Order operations ──────────────────────────────────────────────────────
    #
    # place_order submits a REAL order to the configured endpoint (testnet when
    # testnet=True, otherwise live). It is deliberately gated upstream: the router
    # only routes to a live exchange when live_trading_enabled is true AND the
    # micro-live gate approves. On testnet this exercises the full order pipeline
    # with fake money and zero financial risk.

    async def _symbol_constraints(self, symbol: str) -> SymbolConstraints | None:
        """Load and cache LOT_SIZE / tick / MIN_NOTIONAL constraints for a symbol."""
        cached = self._constraints_cache.get(symbol)
        if cached is not None:
            return cached
        async with request_slot("binance"):
            self._assert_request_allowed()
            try:
                markets = await self._client.load_markets()
                self._record_rate_limit_headers()
            except Exception as e:
                raise self._handle_ccxt_error(e) from e
        constraints = _constraints_from_market(cast(dict[str, Any], markets.get(symbol, {})))
        if constraints is not None:
            self._constraints_cache[symbol] = constraints
        return constraints

    async def reference_price(self, symbol: str) -> Decimal | None:
        """Return the last traded price (for notional validation / order sizing)."""
        async with request_slot("binance"):
            self._assert_request_allowed()
            try:
                ticker = await self._client.fetch_ticker(symbol)
                self._record_rate_limit_headers()
            except Exception as e:
                raise self._handle_ccxt_error(e) from e
        last = ticker.get("last") or ticker.get("close")
        return Decimal(str(last)) if last else None

    async def place_order(self, order: Any) -> dict[str, Any]:
        """Submit a real spot order after quantizing to exchange constraints.

        Fails closed if constraints cannot be loaded or the order violates
        LOT_SIZE / MIN_NOTIONAL. The client_order_id is passed through as Binance
        newClientOrderId so retries are idempotent exchange-side.
        """
        req: OrderRequest = order
        constraints = await self._symbol_constraints(req.symbol)
        ref_price = req.limit_price or await self.reference_price(req.symbol)
        if ref_price is None:
            raise OrderRejectedError(f"no reference price available for {req.symbol}")

        validation = self._validator.validate(req.symbol, req.quantity, ref_price, constraints)
        if not validation.approved:
            raise OrderRejectedError(validation.reason)
        adj_qty = validation.adjusted_qty or req.quantity

        price_arg = float(req.limit_price) if req.order_type == OrderType.LIMIT else None
        params = {"newClientOrderId": req.client_order_id[:36]}

        async with request_slot("binance"):
            self._assert_request_allowed()
            with (
                start_span(
                    "exchange.place_order",
                    {"exchange": "binance", "symbol": req.symbol, "side": req.side.value},
                ),
                API_LATENCY.labels(exchange="binance", method="place_order").time(),
            ):
                try:
                    raw = await self._client.create_order(
                        req.symbol,
                        req.order_type.value,
                        req.side.value,
                        float(adj_qty),
                        price_arg,
                        params,
                    )
                    self._record_rate_limit_headers()
                except Exception as e:
                    raise self._handle_ccxt_error(e) from e

        log.info(
            "binance_order_placed",
            symbol=req.symbol,
            side=req.side.value,
            requested_qty=str(req.quantity),
            adjusted_qty=str(adj_qty),
            testnet=self._testnet,
            order_id=str(raw.get("id", "")),
        )
        return _parse_order_response(cast(dict[str, Any], raw), adj_qty)

    async def cancel_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]:
        """Cancel an open order by its exchange order id."""
        async with request_slot("binance"):
            self._assert_request_allowed()
            try:
                raw = await self._client.cancel_order(exchange_order_id, symbol)
                self._record_rate_limit_headers()
            except Exception as e:
                raise self._handle_ccxt_error(e) from e
        return cast(dict[str, Any], raw)

    async def get_order_status(self, exchange_order_id: str, symbol: str) -> dict[str, Any]:
        """Poll an order's current status (fallback when no WebSocket fill arrives)."""
        async with request_slot("binance"):
            self._assert_request_allowed()
            try:
                raw = await self._client.fetch_order(exchange_order_id, symbol)
                self._record_rate_limit_headers()
            except Exception as e:
                raise self._handle_ccxt_error(e) from e
        return cast(dict[str, Any], raw)

    async def health_check(self) -> bool:
        """Verify Binance is reachable and (if configured) credentials are valid.

        Returns False (without raising) if circuit is open — health_check is polled
        frequently and we never want it to itself trigger ban-recovery noise.
        """
        if check_circuit("binance") > 0:
            log.debug("binance_health_skipped_circuit_open")
            return False
        async with request_slot("binance"):
            if check_circuit("binance") > 0 or check_rate_limit_cooldown("binance") > 0:
                log.debug("binance_health_skipped_circuit_open")
                return False
            try:
                await self._client.fetch_time()
                self._record_rate_limit_headers()
                log.debug("binance_health_ok", testnet=self._testnet)
                return True
            except Exception as e:
                # Trip the circuit if this exposed a ban (don't re-raise — health_check
                # callers expect a bool return).
                self._handle_ccxt_error(e)
                log.warning("binance_health_failed", error=str(e), testnet=self._testnet)
                return False


def _constraints_from_market(market: dict[str, Any]) -> SymbolConstraints | None:
    """Build SymbolConstraints from a CCXT market dict (Binance uses TICK_SIZE mode)."""
    if not market:
        return None
    try:
        limits = market.get("limits", {})
        precision = market.get("precision", {})
        amount_limits = limits.get("amount") or {}
        cost_limits = limits.get("cost") or {}
        qty_step = precision.get("amount")
        tick = precision.get("price")
        if qty_step is None or tick is None:
            return None
        return SymbolConstraints(
            symbol=market["symbol"],
            base_asset=market.get("base", ""),
            quote_asset=market.get("quote", ""),
            min_qty=Decimal(str(amount_limits.get("min") or "0")),
            max_qty=Decimal(str(amount_limits.get("max") or "999999999")),
            qty_step=Decimal(str(qty_step)),
            tick_size=Decimal(str(tick)),
            min_notional=Decimal(str(cost_limits.get("min") or "0")),
        )
    except Exception:
        return None


def _parse_order_response(raw: dict[str, Any], requested_qty: Decimal) -> dict[str, Any]:
    """Normalise a CCXT order response into the router's expected fill dict."""
    filled = Decimal(str(raw.get("filled") or 0))
    avg = raw.get("average") or raw.get("price")
    fill_price = Decimal(str(avg)) if avg else Decimal("0")
    fee = raw.get("fee")
    fee_paid = Decimal(str(fee.get("cost") or 0)) if isinstance(fee, dict) and fee else Decimal("0")
    if filled <= 0:
        status = "pending"
    elif filled < requested_qty:
        status = "partially_filled"
    else:
        status = "filled"
    return {
        "exchange_order_id": str(raw.get("id") or ""),
        "fill_price": str(fill_price),
        "filled_quantity": str(filled),
        "fee_paid": str(fee_paid),
        "slippage_cost": "0",
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
    }


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
