"""Paper trading exchange — simulates fills without touching real exchange.

Implements ExchangeInterface. All orders are treated as market orders and
fill immediately at the current WebSocket price + slippage. No partial fills,
no order queue.

State is in-memory and resets on restart.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trading_bot.core.contracts import ExchangeInterface
from trading_bot.core.exceptions import OrderRejectedError
from trading_bot.core.models import OrderRequest, OrderSide
from trading_bot.observability.logging import get_logger
from trading_bot.websocket.price_cache import get_price_cache

log = get_logger(__name__)

_SLIPPAGE = Decimal("0.0005")  # 0.05% market impact


class PaperExchange(ExchangeInterface):
    """Simulates market-order fills at current WebSocket price."""

    async def place_order(self, order: Any) -> dict[str, Any]:
        req: OrderRequest = order
        raw_price = self._resolve_price(req.symbol)
        if raw_price is None:
            raise OrderRejectedError(
                f"No live price available for {req.symbol} — WebSocket may be disconnected"
            )

        fill_price = (
            raw_price * (1 + _SLIPPAGE)
            if req.side == OrderSide.BUY
            else raw_price * (1 - _SLIPPAGE)
        )

        log.info(
            "paper_order_filled",
            symbol=req.symbol,
            side=req.side,
            quantity=str(req.quantity),
            fill_price=str(fill_price),
            order_id=req.client_order_id,
        )
        return {
            "exchange_order_id": f"PAPER-{req.client_order_id}",
            "fill_price": str(fill_price),
            "filled_quantity": str(req.quantity),
            "status": "filled",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _resolve_price(self, symbol: str) -> Decimal | None:
        # Symbol normalisation: "BTC/USDT" → "BTCUSDT"
        ws_symbol = symbol.replace("/", "")
        tick = get_price_cache().get(ws_symbol)
        if tick is not None:
            return tick.price
        return None

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Any = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError("PaperExchange does not fetch OHLCV — use BinanceExchange")

    async def cancel_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]:
        return {}

    async def fetch_balances(self) -> dict[str, Decimal]:
        from trading_bot.portfolio.manager import get_portfolio_manager

        snap = get_portfolio_manager().get_snapshot()
        return {"USDT": snap.cash_balance}

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        return []

    async def fetch_trade_fees(self, symbol: str) -> dict[str, Decimal]:
        return {"maker": Decimal("0.001"), "taker": Decimal("0.001")}

    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        return {}

    async def get_server_time(self) -> datetime:
        return datetime.now(UTC)

    async def health_check(self) -> bool:
        return True
