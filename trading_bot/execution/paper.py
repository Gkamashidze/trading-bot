"""Paper trading exchange — simulates fills without touching real exchange.

Implements ExchangeInterface. Uses RealisticFillModel (REALISTIC profile) by
default to produce fills that account for bid/ask spread, taker fees, market
impact, partial fills, latency, and stale quote rejection.

Set fill_model_profile=FillModelProfile.IDEAL to restore legacy instant-fill
behavior (useful for debugging strategy logic in isolation).

State is in-memory and resets on restart.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trading_bot.backtesting.fill_model import (
    FillModel,
    FillModelProfile,
    PerfectFillModel,
    RealisticFillModel,
)
from trading_bot.core.contracts import ExchangeInterface
from trading_bot.core.exceptions import OrderRejectedError
from trading_bot.core.models import OrderRequest, OrderSide
from trading_bot.observability.logging import get_logger
from trading_bot.websocket.price_cache import get_price_cache

log = get_logger(__name__)


class PaperExchange(ExchangeInterface):
    """Simulates fills via a configurable FillModel.

    Default: RealisticFillModel (REALISTIC profile).
    """

    def __init__(
        self,
        fill_model_profile: FillModelProfile = FillModelProfile.REALISTIC,
        rng_seed: int | None = None,
    ) -> None:
        _model: FillModel
        if fill_model_profile == FillModelProfile.IDEAL:
            _model = PerfectFillModel()
        else:
            _model = RealisticFillModel.from_profile(fill_model_profile)
        self._fill_model = _model
        self._rng = random.Random(rng_seed)  # noqa: S311

    async def place_order(self, order: Any) -> dict[str, Any]:
        req: OrderRequest = order
        raw_price = self._resolve_price(req.symbol)
        if raw_price is None:
            raise OrderRejectedError(
                f"No live price available for {req.symbol} — WebSocket may be disconnected"
            )

        ref_price = float(raw_price)
        qty = float(req.quantity)

        if req.side == OrderSide.BUY:
            result = self._fill_model.simulate_buy(ref_price, qty, rng=self._rng)
        else:
            result = self._fill_model.simulate_sell(ref_price, qty, rng=self._rng)

        if result.rejected:
            raise OrderRejectedError(
                f"Paper fill rejected for {req.symbol}: {result.reject_reason}"
            )

        fill_price = Decimal(str(result.net_fill_price))
        filled_qty = Decimal(str(result.filled_quantity))
        status = "partially_filled" if result.is_partial else "filled"

        log.info(
            "paper_order_filled",
            symbol=req.symbol,
            side=req.side,
            requested_quantity=str(req.quantity),
            filled_quantity=str(filled_qty),
            gross_price=str(result.gross_fill_price),
            net_fill_price=str(fill_price),
            fee_paid=str(result.fee_paid),
            slippage_cost=str(result.slippage_cost),
            latency_ms=result.latency_ms,
            is_partial=result.is_partial,
            order_id=req.client_order_id,
        )
        return {
            "exchange_order_id": f"PAPER-{req.client_order_id}",
            "fill_price": str(fill_price),
            "filled_quantity": str(filled_qty),
            "fee_paid": str(result.fee_paid),
            "slippage_cost": str(result.slippage_cost),
            "status": status,
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
