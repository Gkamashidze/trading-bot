"""Operator-controlled micro-live order execution.

This is the ONLY path that can place a real (or testnet) order. It is
deliberately NOT wired into the auto-scheduler — every order is an explicit
operator action. Given the baseline strategies have no demonstrated edge
(docs/strategies/backtest_reports/), auto-live-trading would be auto-loss;
micro-live exists only to validate the execution/safety machinery end-to-end.

Fails closed at every gate:
  1. ``live_trading_enabled`` feature flag (default false)
  2. ``MicroLiveGate`` — session active, daily approval, $50 / $25 / $75 caps,
     no pyramiding (and its own ``_MICRO_LIVE_GLOBALLY_ENABLED`` code constant)
  3. exchange-side LOT_SIZE / MIN_NOTIONAL validation inside ``place_order``

On testnet this exercises the whole path with fake money and zero risk.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast

from trading_bot.core.models import (
    ExchangeId,
    OrderRequest,
    OrderSide,
    OrderState,
    OrderStatus,
    OrderType,
)
from trading_bot.observability.logging import get_logger
from trading_bot.promotion.micro_live import MicroLiveGate

log = get_logger(__name__)

_TAKER_FEE_RATE = Decimal("0.001")


class MicroLiveRefusedError(Exception):
    """Raised when a micro-live order is refused by any safety gate."""


class MicroLiveExecutor:
    """Places one gated micro-live order per explicit operator call."""

    def __init__(
        self, exchange: object, gate: MicroLiveGate, *, strategy_id: str = "operator"
    ) -> None:
        self._exchange = exchange
        self._gate = gate
        self._strategy_id = strategy_id

    async def submit(
        self,
        *,
        symbol: str,
        side: str,
        usd_notional: Decimal | float | str,
        operator: str,
    ) -> dict[str, object]:
        """Submit one micro-live order. Raises MicroLiveRefusedError if any gate blocks."""
        from trading_bot.feature_flags import is_enabled

        # ── Gate 1: master feature flag ───────────────────────────────────────
        if not await is_enabled("live_trading_enabled"):
            raise MicroLiveRefusedError("live_trading_enabled is false — refusing live order")

        notional = Decimal(str(usd_notional))
        price = await self._exchange.reference_price(symbol)  # type: ignore[attr-defined]
        if price is None or price <= 0:
            raise MicroLiveRefusedError(f"no reference price available for {symbol}")

        from trading_bot.portfolio.manager import get_portfolio_manager

        portfolio = get_portfolio_manager()
        snapshot = portfolio.get_snapshot()
        open_positions = len([p for p in snapshot.positions if p.quantity > 0])

        # ── Gate 2: micro-live gate (caps, approval, pyramiding, global flag) ──
        allowed, reason = self._gate.is_order_allowed(
            self._strategy_id, symbol, notional, open_positions
        )
        if not allowed:
            raise MicroLiveRefusedError(f"micro-live gate refused: {reason}")

        side_enum = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        qty = notional / price
        order = OrderRequest(
            symbol=symbol,
            exchange=ExchangeId.BINANCE,
            side=side_enum,
            order_type=OrderType.MARKET,
            quantity=qty,
            strategy_id=self._strategy_id,
        )

        log.warning(
            "micro_live_order_submitting",
            symbol=symbol,
            side=side_enum.value,
            usd_notional=str(notional),
            operator=operator,
        )

        # ── Gate 3: exchange-side precision/notional validation in place_order ─
        raw = await self._exchange.place_order(order)  # type: ignore[attr-defined]
        fill = cast("dict[str, object]", raw)
        await self._record_fill(order, fill, side_enum)
        return fill

    async def _record_fill(
        self, order: OrderRequest, fill: dict[str, object], side: OrderSide
    ) -> None:
        """Mirror the paper path's bookkeeping for a real fill."""
        actual_price = Decimal(str(fill["fill_price"]))
        actual_qty = Decimal(str(fill["filled_quantity"]))
        if actual_qty <= 0:
            log.error("micro_live_zero_fill", order_id=order.client_order_id)
            return

        from trading_bot.accounting.ledger import get_accounting_ledger
        from trading_bot.oms.tracker import get_order_tracker
        from trading_bot.portfolio.manager import get_portfolio_manager

        get_portfolio_manager().apply_fill(order, actual_price, filled_quantity=actual_qty)

        get_order_tracker().record(
            OrderState(
                client_order_id=order.client_order_id,
                exchange_order_id=str(fill.get("exchange_order_id", "")),
                symbol=order.symbol,
                exchange=order.exchange,
                side=order.side,
                order_type=order.order_type,
                requested_quantity=order.quantity,
                filled_quantity=actual_qty,
                average_fill_price=actual_price,
                status=OrderStatus.FILLED,
                strategy_id=order.strategy_id,
            )
        )

        fee = actual_qty * actual_price * _TAKER_FEE_RATE
        ledger = get_accounting_ledger()
        lot = ledger.record_trade(
            symbol=order.symbol,
            side=side.value,
            quantity=actual_qty,
            price=actual_price,
            fee_usdt=fee,
            order_id=order.client_order_id,
        )
        realized = ledger.realized_for_sell(lot.lot_id) if side == OrderSide.SELL else None
        realized_pnl = realized[0] if realized is not None else Decimal("0")

        # Update micro-live loss budgets (may auto-rollback to paper on breach).
        self._gate.record_fill(realized_pnl, actual_qty * actual_price)

        from trading_bot.evidence.recorder import record_fill_evidence

        await record_fill_evidence(
            order_id=order.client_order_id,
            symbol=order.symbol,
            strategy_id=order.strategy_id or self._strategy_id,
            side=side.value,
            signal_price=actual_price,
            fill_price=actual_price,
            quantity=actual_qty,
            fee_paid=fee,
            slippage_pct=0,
            slippage_usdt=0,
            latency_ms=0,
            quality_score="excellent",
            outcome="filled",
            realized_pnl=realized_pnl if realized is not None else None,
            cost_basis=realized[1] if realized is not None else None,
            lot_id=lot.lot_id,
        )
        log.warning(
            "micro_live_order_executed",
            order_id=order.client_order_id,
            symbol=order.symbol,
            side=side.value,
            fill_price=str(actual_price),
            filled_qty=str(actual_qty),
        )
