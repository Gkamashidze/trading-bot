"""Order router — converts strategy signals to paper trades.

Flow per signal:
  StrategyResult (BUY/SELL/HOLD)
    → only act when signal *changes* from the previous refresh
    → size the position (20% of available cash per BUY)
    → RiskEngine.pre_trade_check()
    → PaperExchange.place_order()
    → PortfolioManager.apply_fill()
    → OrderTracker.record()

Only BUY and SELL signals trigger execution. HOLD is a no-op.
Signal-change tracking prevents buying repeatedly while already positioned.
"""

from __future__ import annotations

from decimal import Decimal

from trading_bot.core.models import (
    ExchangeId,
    OrderRequest,
    OrderSide,
    OrderState,
    OrderStatus,
    OrderType,
)
from trading_bot.execution.paper import PaperExchange
from trading_bot.observability.logging import get_logger
from trading_bot.oms.tracker import get_order_tracker
from trading_bot.portfolio.manager import get_portfolio_manager
from trading_bot.risk.engine import RiskEngine
from trading_bot.strategies.base import StrategyResult

log = get_logger(__name__)

# Symbol: "BTC/USDT" in position/order models, "BTCUSDT" in WebSocket
_ORDER_SYMBOL = "BTC/USDT"
_POSITION_FRACTION = Decimal("0.20")  # invest 20% of available cash per BUY
_MIN_ORDER_VALUE = Decimal("10")  # skip orders worth less than $10

_risk = RiskEngine()
_exchange = PaperExchange()

# Last observed signal per strategy — used to detect signal transitions
_last_signal: dict[str, str] = {}


async def route_signal(result: StrategyResult) -> None:
    """Route a single StrategyResult to the paper exchange.

    Only acts on BUY/SELL signals, and only when the signal changed from
    the previous refresh to avoid duplicate trades on sustained signals.
    """
    prev = _last_signal.get(result.strategy_id, "HOLD")
    _last_signal[result.strategy_id] = result.signal

    if result.signal not in ("BUY", "SELL"):
        return
    if result.signal == prev:
        log.debug(
            "router_skip_repeated_signal",
            strategy=result.strategy_id,
            signal=result.signal,
        )
        return

    portfolio = get_portfolio_manager()
    tracker = get_order_tracker()
    snapshot = portfolio.get_snapshot()

    # ── Resolve current price from WebSocket ─────────────────────────────────
    from trading_bot.websocket.price_cache import get_price_cache

    tick = get_price_cache().get("BTCUSDT")
    if tick is None:
        log.warning(
            "router_no_price", symbol="BTCUSDT", signal=result.signal, strategy=result.strategy_id
        )
        return

    fill_price = tick.price
    side = OrderSide.BUY if result.signal == "BUY" else OrderSide.SELL

    # ── Position sizing ──────────────────────────────────────────────────────
    if side == OrderSide.BUY:
        invest = snapshot.cash_balance * _POSITION_FRACTION
        if invest < _MIN_ORDER_VALUE:
            log.debug("router_skip_small_order", invest=str(invest), strategy=result.strategy_id)
            return
        quantity = (invest / fill_price).quantize(Decimal("0.000001"))
    else:
        pos = next((p for p in snapshot.positions if p.symbol == _ORDER_SYMBOL), None)
        if pos is None:
            log.debug("router_no_position_to_sell", strategy=result.strategy_id)
            return
        quantity = pos.quantity

    if quantity <= 0:
        return

    order = OrderRequest(
        symbol=_ORDER_SYMBOL,
        exchange=ExchangeId.BINANCE,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        strategy_id=result.strategy_id,
    )

    # ── Risk check ───────────────────────────────────────────────────────────
    decision = _risk.pre_trade_check(order, snapshot, fill_price)
    if not decision.approved:
        log.warning(
            "router_risk_rejected",
            strategy=result.strategy_id,
            signal=result.signal,
            reason=decision.reason,
            tier=decision.tier,
        )
        tracker.record(
            OrderState(
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                exchange=order.exchange,
                side=order.side,
                order_type=order.order_type,
                requested_quantity=order.quantity,
                status=OrderStatus.REJECTED,
                reject_reason=decision.reason,
                strategy_id=order.strategy_id,
            )
        )
        return

    # ── Execute on paper exchange ────────────────────────────────────────────
    try:
        fill_resp = await _exchange.place_order(order)
        actual_price = Decimal(fill_resp["fill_price"])
        portfolio.apply_fill(order, actual_price)
        tracker.record(
            OrderState(
                client_order_id=order.client_order_id,
                exchange_order_id=fill_resp.get("exchange_order_id", ""),
                symbol=order.symbol,
                exchange=order.exchange,
                side=order.side,
                order_type=order.order_type,
                requested_quantity=order.quantity,
                filled_quantity=order.quantity,
                average_fill_price=actual_price,
                status=OrderStatus.FILLED,
                strategy_id=order.strategy_id,
            )
        )
    except Exception as e:
        log.error("router_execution_error", error=str(e), symbol=order.symbol)


async def route_signals(results: list[StrategyResult]) -> None:
    """Route all strategy results. Called after each signal refresh."""
    for result in results:
        await route_signal(result)
