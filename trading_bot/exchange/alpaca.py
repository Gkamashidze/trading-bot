"""Alpaca ETF/equity exchange adapter.

Implements ExchangeInterface for Alpaca paper and live trading.
Default mode is always paper (https://paper-api.alpaca.markets).

Live trading requires ALL of the following:
  1. paper=False in AlpacaExchangeSettings
  2. ALLOW_LIVE_TRADING=true environment variable (allow_live_trading=True)
  3. live_trading_enabled feature flag = True (checked externally by the router)

Raises KillSwitchError at construction if live is attempted without opt-in.

Security:
  - API key and secret are NEVER logged (structlog keys are filtered).
  - Symbol allowlist is enforced before every order call.
  - US equity market hours are enforced before every order call.
  - All sync alpaca-py calls run in the thread-pool executor (never block the loop).

Key rotation: every 90 days. Set calendar reminder.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from typing import Any

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.enums import QueryOrderStatus
from alpaca.trading.enums import TimeInForce as AlpacaTimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
)

from trading_bot.core.contracts import ExchangeInterface
from trading_bot.core.exceptions import (
    ExchangeAuthError,
    ExchangeConnectionError,
    ExchangeOrderError,
    ExchangeRateLimitError,
    KillSwitchError,
)
from trading_bot.observability.logging import get_logger
from trading_bot.observability.metrics import API_LATENCY
from trading_bot.utils.market_calendar import is_equity_market_open

log = get_logger(__name__)

_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_LIVE_BASE_URL = "https://api.alpaca.markets"

_DEFAULT_ALLOWED_SYMBOLS: frozenset[str] = frozenset({"SPY", "QQQ", "SOXX", "IBIT"})

_TIMEFRAME_MAP: dict[str, Any] = {
    "1m": TimeFrame.Minute,
    "5m": TimeFrame(5, TimeFrameUnit.Minute),
    "15m": TimeFrame(15, TimeFrameUnit.Minute),
    "30m": TimeFrame(30, TimeFrameUnit.Minute),
    "1h": TimeFrame.Hour,
    "4h": TimeFrame(4, TimeFrameUnit.Hour),
    "1d": TimeFrame.Day,
    "1w": TimeFrame.Week,
}


class AlpacaExchange(ExchangeInterface):
    """Alpaca paper/live adapter for US ETF and equity trading.

    Thread-safety: NOT thread-safe across OS threads.
    Use one instance per asyncio event loop.
    All blocking alpaca-py SDK calls run in the thread-pool executor.
    """

    def __init__(
        self,
        api_key: str = "",
        secret_key: str = "",
        paper: bool = True,
        allowed_symbols: frozenset[str] = _DEFAULT_ALLOWED_SYMBOLS,
        trading_base_url: str = _PAPER_BASE_URL,
        allow_live_trading: bool = False,
    ) -> None:
        """Initialise the Alpaca adapter.

        Args:
            api_key: Alpaca API key (ALPACA_API_KEY env var).
            secret_key: Alpaca secret key (ALPACA_SECRET_KEY env var).
            paper: True → paper endpoint (default, safe). False → live.
            allowed_symbols: ETF/equity symbols that may be ordered.
                Orders for symbols not in this set are rejected immediately.
            trading_base_url: Override for the Alpaca trading API base URL.
                Passed as url_override to TradingClient. Defaults to the paper
                endpoint. The data API (StockHistoricalDataClient) always uses
                its own default endpoint (data.alpaca.markets) — separate URLs.
            allow_live_trading: Must be True (ALLOW_LIVE_TRADING=true) when
                paper=False. Raises KillSwitchError otherwise.
        """
        if not paper and not allow_live_trading:
            raise KillSwitchError(
                "Live Alpaca trading is blocked. "
                "Set ALLOW_LIVE_TRADING=true AND paper=false in AlpacaExchangeSettings. "
                "See runbook: trading_bot/docs/runbooks/live_trading_checklist.md"
            )

        self._paper = paper
        self._allowed_symbols = frozenset(s.upper() for s in allowed_symbols)

        self._trading = TradingClient(
            api_key=api_key or None,
            secret_key=secret_key or None,
            paper=paper,
            url_override=trading_base_url,
        )
        # Data API uses its own endpoint (data.alpaca.markets) — not the trading URL.
        self._data_client = StockHistoricalDataClient(
            api_key=api_key or None,
            secret_key=secret_key or None,
        )

        log.info(
            "alpaca_adapter_created",
            paper=paper,
            allowed_symbols=sorted(self._allowed_symbols),
            live_trading_armed=(not paper and allow_live_trading),
        )

    # ── Internal helpers ────────────────────────────────────────────────────

    async def _run_sync(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a synchronous alpaca-py SDK call in the default thread-pool executor.

        Never call blocking SDK methods directly from async context — they hold
        the event loop and break all concurrent coroutines.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(fn, *args, **kwargs))

    def _validate_symbol(self, symbol: str) -> None:
        """Reject orders for symbols not in the configured allowlist."""
        if symbol.upper() not in self._allowed_symbols:
            raise ExchangeOrderError(
                f"Symbol '{symbol}' is not in the Alpaca ETF allowlist "
                f"({sorted(self._allowed_symbols)}). "
                "Add it to AlpacaExchangeSettings.allowed_etf_symbols."
            )

    async def _is_market_open(self) -> bool:
        """Check market status via Alpaca /clock endpoint (authoritative).

        Falls back to pandas-market-calendars on connection failure.
        """
        try:
            clock = await self._run_sync(self._trading.get_clock)
            return bool(clock.is_open)
        except Exception:
            return is_equity_market_open()

    # ── ExchangeInterface ────────────────────────────────────────────────────

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV bars from Alpaca Stock Historical Data API.

        Returns a list of dicts matching the project's standard OHLCV schema
        (open_time, open, high, low, close, volume as Decimal, UTC timestamps).
        """
        if timeframe not in _TIMEFRAME_MAP:
            raise ExchangeOrderError(
                f"Unsupported timeframe '{timeframe}'. Supported: {sorted(_TIMEFRAME_MAP)}"
            )
        alpaca_tf = _TIMEFRAME_MAP[timeframe]

        request_params: dict[str, Any] = {
            "symbol_or_symbols": symbol.upper(),
            "timeframe": alpaca_tf,
            "limit": limit,
        }
        if since is not None:
            request_params["start"] = since

        with API_LATENCY.labels(exchange="alpaca", method="fetch_ohlcv").time():
            try:
                request = StockBarsRequest(**request_params)
                response = await self._run_sync(self._data_client.get_stock_bars, request)
                raw_bars = list(response.data.get(symbol.upper(), []))
            except Exception as exc:
                _raise_alpaca_error(exc, context=f"fetch_ohlcv({symbol})")

        result: list[dict[str, Any]] = []
        for bar in raw_bars:
            ts: datetime = bar.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            result.append(
                {
                    "open_time": ts,
                    "open": Decimal(str(bar.open)),
                    "high": Decimal(str(bar.high)),
                    "low": Decimal(str(bar.low)),
                    "close": Decimal(str(bar.close)),
                    "volume": Decimal(str(bar.volume)),
                    "quote_volume": Decimal("0"),
                    "trade_count": getattr(bar, "trade_count", None),
                    "close_time": ts,
                }
            )
        return result

    async def place_order(self, order: Any) -> dict[str, Any]:
        """Submit a paper or live equity order to Alpaca.

        Guards (evaluated in order):
          1. Symbol must be in the configured allowlist.
          2. US equity market must be open (Alpaca /clock).
          3. Order type must be MARKET or LIMIT.

        Logs signal details at INFO level:
          broker, paper mode, symbol, side, qty, order_type,
          exchange_order_id, fill_price, filled_quantity, status.
        """
        from trading_bot.core.models import OrderSide, OrderType

        req = order  # OrderRequest
        self._validate_symbol(req.symbol)

        market_open = await self._is_market_open()
        if not market_open:
            log.warning(
                "alpaca_order_skipped_market_closed",
                broker="alpaca",
                paper=self._paper,
                symbol=req.symbol,
                side=str(req.side),
                quantity=str(req.quantity),
            )
            raise ExchangeOrderError(
                f"US equity market is closed — order for {req.symbol} skipped. "
                "The scheduler will retry on the next market-open signal."
            )

        log.info(
            "alpaca_signal_order_submitted",
            broker="alpaca",
            paper=self._paper,
            symbol=req.symbol,
            side=str(req.side),
            quantity=str(req.quantity),
            order_type=str(req.order_type),
            strategy_id=getattr(req, "strategy_id", ""),
        )

        alpaca_side = AlpacaOrderSide.BUY if req.side == OrderSide.BUY else AlpacaOrderSide.SELL
        alpaca_tif = AlpacaTimeInForce.DAY  # ETF orders always DAY — prevents stale GTC risk

        try:
            if req.order_type == OrderType.MARKET:
                alpaca_request: MarketOrderRequest | LimitOrderRequest = MarketOrderRequest(
                    symbol=req.symbol.upper(),
                    qty=float(req.quantity),
                    side=alpaca_side,
                    time_in_force=alpaca_tif,
                )
            elif req.order_type == OrderType.LIMIT:
                alpaca_request = LimitOrderRequest(
                    symbol=req.symbol.upper(),
                    qty=float(req.quantity),
                    side=alpaca_side,
                    limit_price=float(req.limit_price),
                    time_in_force=alpaca_tif,
                )
            else:
                raise ExchangeOrderError(
                    f"Order type '{req.order_type}' is not supported by AlpacaExchange. "
                    "Supported types: MARKET, LIMIT."
                )

            result = await self._run_sync(self._trading.submit_order, alpaca_request)

        except ExchangeOrderError:
            raise
        except Exception as exc:
            _raise_alpaca_error(exc, context=f"place_order({req.symbol})")

        fill_price = getattr(result, "filled_avg_price", None)
        filled_qty = getattr(result, "filled_qty", None)
        status = getattr(result.status, "value", str(result.status))
        created_at = getattr(result, "created_at", None)

        log.info(
            "alpaca_order_acknowledged",
            broker="alpaca",
            paper=self._paper,
            symbol=req.symbol,
            side=str(req.side),
            exchange_order_id=str(result.id),
            fill_price=str(fill_price) if fill_price else "pending",
            filled_quantity=str(filled_qty) if filled_qty else "0",
            status=status,
        )

        return {
            "exchange_order_id": str(result.id),
            "fill_price": str(fill_price) if fill_price else "0",
            "filled_quantity": str(filled_qty) if filled_qty else "0",
            "fee_paid": "0",  # Alpaca is commission-free for US ETFs/equities
            "slippage_cost": "0",
            "status": status,
            "timestamp": created_at.isoformat() if created_at else datetime.now(UTC).isoformat(),
        }

    async def cancel_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]:
        try:
            order_uuid = uuid.UUID(exchange_order_id)
            await self._run_sync(self._trading.cancel_order_by_id, order_uuid)
        except Exception as exc:
            _raise_alpaca_error(exc, context=f"cancel_order({exchange_order_id})")

        log.info(
            "alpaca_order_cancelled",
            broker="alpaca",
            exchange_order_id=exchange_order_id,
            symbol=symbol,
        )
        return {"exchange_order_id": exchange_order_id, "status": "cancelled"}

    async def fetch_balances(self) -> dict[str, Decimal]:
        """Return account cash and portfolio value as {asset: amount}."""
        try:
            account = await self._run_sync(self._trading.get_account)
        except Exception as exc:
            _raise_alpaca_error(exc, context="fetch_balances")
        return {
            "USD": Decimal(str(account.cash)),
            "portfolio_value": Decimal(str(account.portfolio_value)),
        }

    async def fetch_account(self) -> dict[str, Any]:
        """Return full account snapshot: equity, cash, buying_power, P&L, day_trade_count."""
        try:
            account = await self._run_sync(self._trading.get_account)
        except Exception as exc:
            _raise_alpaca_error(exc, context="fetch_account")
        return {
            "equity": str(account.equity),
            "cash": str(account.cash),
            "portfolio_value": str(account.portfolio_value),
            "buying_power": str(account.buying_power),
            "last_equity": str(account.last_equity),
            "status": getattr(account.status, "value", str(account.status)),
            "paper": self._paper,
        }

    async def fetch_positions(self) -> list[dict[str, Any]]:
        """Return all open positions from Alpaca account."""
        try:
            positions = await self._run_sync(self._trading.get_all_positions)
        except Exception as exc:
            _raise_alpaca_error(exc, context="fetch_positions")
        result: list[dict[str, Any]] = []
        for p in positions:
            result.append(
                {
                    "symbol": p.symbol,
                    "qty": str(p.qty),
                    "avg_entry_price": str(p.avg_entry_price),
                    "current_price": str(p.current_price),
                    "market_value": str(p.market_value),
                    "unrealized_pl": str(p.unrealized_pl),
                    "unrealized_plpc": str(p.unrealized_plpc),
                    "side": getattr(p.side, "value", str(p.side)),
                }
            )
        return result

    async def get_server_time(self) -> datetime:
        """Return current Alpaca server time as UTC-aware datetime."""
        try:
            clock = await self._run_sync(self._trading.get_clock)
            ts: datetime = clock.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            return ts
        except Exception as exc:
            _raise_alpaca_error(exc, context="get_server_time")
            raise  # unreachable — _raise_alpaca_error always raises

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        try:
            req = GetOrdersRequest(status=QueryOrderStatus.OPEN)
            orders = await self._run_sync(self._trading.get_orders, req)
        except Exception as exc:
            _raise_alpaca_error(exc, context="fetch_open_orders")

        result: list[dict[str, Any]] = []
        for o in orders:
            if symbol and o.symbol != symbol.upper():
                continue
            result.append(
                {
                    "exchange_order_id": str(o.id),
                    "symbol": o.symbol,
                    "side": getattr(o.side, "value", str(o.side)),
                    "qty": str(o.qty),
                    "status": getattr(o.status, "value", str(o.status)),
                }
            )
        return result

    async def fetch_trade_fees(self, symbol: str) -> dict[str, Decimal]:
        """Alpaca is commission-free for US ETFs and equities."""
        return {"maker": Decimal("0"), "taker": Decimal("0")}

    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        """Return asset metadata from Alpaca asset registry."""
        try:
            asset = await self._run_sync(self._trading.get_asset, symbol.upper())
        except Exception as exc:
            _raise_alpaca_error(exc, context=f"get_symbol_info({symbol})")
        return {
            "symbol": symbol.upper(),
            "name": getattr(asset, "name", ""),
            "tradable": getattr(asset, "tradable", True),
            "fractionable": getattr(asset, "fractionable", False),
            "asset_class": str(getattr(asset, "asset_class", "us_equity")),
            "exchange": str(getattr(asset, "exchange", "")),
            "min_qty": "1",
            "qty_step": "1",
            "tick_size": "0.01",
        }

    async def health_check(self) -> bool:
        """Return True if Alpaca account is reachable and ACTIVE."""
        try:
            account = await self._run_sync(self._trading.get_account)
            status_val = getattr(account.status, "value", str(account.status))
            healthy = status_val == "ACTIVE"
            log.debug("alpaca_health_ok", paper=self._paper, account_status=status_val)
            return healthy
        except Exception as exc:
            log.warning("alpaca_health_failed", error=str(exc), paper=self._paper)
            return False


# ── Error mapping ────────────────────────────────────────────────────────────


def _raise_alpaca_error(exc: Exception, *, context: str) -> None:
    """Map alpaca-py / HTTP exceptions to our exception hierarchy and re-raise."""
    err = str(exc).lower()
    log.error("alpaca_api_error", context=context, error=str(exc))
    if "forbidden" in err or "unauthorized" in err or "403" in err or "401" in err:
        raise ExchangeAuthError(f"Alpaca authentication failed in {context}: {exc}") from exc
    if "rate limit" in err or "429" in err:
        raise ExchangeRateLimitError(
            f"Alpaca rate limit exceeded in {context}: {exc}",
            retry_after_seconds=60.0,
        ) from exc
    if "connection" in err or "timeout" in err or "network" in err:
        raise ExchangeConnectionError(f"Alpaca connection error in {context}: {exc}") from exc
    raise ExchangeOrderError(f"Alpaca API error in {context}: {exc}") from exc
