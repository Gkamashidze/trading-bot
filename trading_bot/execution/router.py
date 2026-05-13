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

import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from trading_bot.core.models import (
    ExchangeId,
    OrderRequest,
    OrderSide,
    OrderState,
    OrderStatus,
    OrderType,
)
from trading_bot.execution.paper import PaperExchange
from trading_bot.idempotency.keys import idempotency_key_for_order
from trading_bot.observability.logging import get_logger
from trading_bot.oms.tracker import get_order_tracker
from trading_bot.portfolio.manager import get_portfolio_manager
from trading_bot.risk.engine import RiskEngine
from trading_bot.strategies.base import StrategyResult

log = get_logger(__name__)

_POSITION_FRACTION = Decimal("0.20")  # invest 20% of available cash per BUY
_MIN_ORDER_VALUE = Decimal("10")  # skip orders worth less than $10

_risk = RiskEngine()
_exchange = PaperExchange()

# Persist last signal state across restarts — Railway mounts a volume at /data.
# Derived from DATA_PATH env var so dev and prod use the same code path.
_LAST_SIGNAL_PATH = Path(os.environ.get("DATA_PATH", "data/raw")).parent / "last_signal.json"


def _load_last_signal() -> dict[str, str]:
    try:
        if _LAST_SIGNAL_PATH.exists():
            data: dict[str, str] = json.loads(_LAST_SIGNAL_PATH.read_text())
            log.info("router_last_signal_loaded", path=str(_LAST_SIGNAL_PATH), keys=len(data))
            return data
    except Exception as exc:
        log.warning("router_last_signal_load_failed", path=str(_LAST_SIGNAL_PATH), error=str(exc))
    return {}


def _save_last_signal() -> None:
    try:
        _LAST_SIGNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _LAST_SIGNAL_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_last_signal))
        tmp.replace(_LAST_SIGNAL_PATH)
    except Exception as exc:
        log.warning("router_last_signal_save_failed", path=str(_LAST_SIGNAL_PATH), error=str(exc))


# Last observed signal keyed by "symbol:strategy_id" — detects signal transitions per asset.
# Loaded from disk on startup so restarts don't reset prev=HOLD and re-trigger BUY.
_last_signal: dict[str, str] = _load_last_signal()


def _record_reconciliation_rejection(
    result: StrategyResult,
    tracker: object,
    reason: str,
) -> None:
    """Record an OMS rejection caused by reconciliation block."""
    from trading_bot.oms.tracker import get_order_tracker

    t = get_order_tracker()
    t.record(
        OrderState(
            client_order_id=f"recon_block_{result.symbol}_{result.strategy_id}",
            symbol=result.symbol,
            exchange=ExchangeId.BINANCE,
            side=OrderSide.BUY if result.signal == "BUY" else OrderSide.SELL,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("0"),
            status=OrderStatus.REJECTED,
            reject_reason=reason,
            strategy_id=result.strategy_id,
        )
    )


async def route_signal(result: StrategyResult) -> None:
    """Route a single StrategyResult to the paper exchange.

    Only acts on BUY/SELL signals, and only when the signal changed from
    the previous refresh to avoid duplicate trades on sustained signals.
    """
    from trading_bot.feature_flags import is_enabled
    from trading_bot.safety.circuit_breaker import get_circuit_breaker

    if not await is_enabled("paper_trading_enabled"):
        log.debug("router_kill_switch_active", strategy=result.strategy_id)
        return

    cb = get_circuit_breaker()
    if not cb.is_trading_allowed():
        log.warning(
            "router_circuit_breaker_halt",
            strategy=result.strategy_id,
            tier=cb.current_tier,
            drawdown_pct=f"{cb.last_drawdown_pct:.2%}",
        )
        return

    # ── Reconciliation gate — block new orders if reconciler is critical ─────
    from trading_bot.oms.reconciler import ReconciliationSeverity, get_reconciler

    reconciler = get_reconciler()
    if reconciler is not None:
        if reconciler.orders_blocked:
            log.error(
                "router_reconciliation_block",
                strategy=result.strategy_id,
                signal=result.signal,
                note="new orders blocked — critical reconciliation mismatch",
            )
            tracker = get_order_tracker()
            # Record the rejection so operators can see blocked orders in /open_orders
            _record_reconciliation_rejection(result, tracker, "reconciliation_critical_block")
            return
        if reconciler.last_report is not None:
            if reconciler.last_report.severity == ReconciliationSeverity.CRITICAL:
                log.error(
                    "router_reconciliation_critical_severity",
                    strategy=result.strategy_id,
                    signal=result.signal,
                )
                tracker = get_order_tracker()
                _record_reconciliation_rejection(
                    result, tracker, "reconciliation_severity_critical"
                )
                return

    signal_key = f"{result.symbol}:{result.strategy_id}"
    prev = _last_signal.get(signal_key, "HOLD")
    _last_signal[signal_key] = result.signal
    _save_last_signal()

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

    ws_symbol = result.symbol.replace("/", "").upper()  # "ETH/USDT" → "ETHUSDT"
    tick = get_price_cache().get(ws_symbol)
    if tick is None:
        log.warning(
            "router_no_price",
            symbol=ws_symbol,
            signal=result.signal,
            strategy=result.strategy_id,
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
        pos = next((p for p in snapshot.positions if p.symbol == result.symbol), None)
        if pos is None:
            log.debug(
                "router_no_position_to_sell",
                symbol=result.symbol,
                strategy=result.strategy_id,
            )
            return
        quantity = pos.quantity

    if quantity <= 0:
        return

    # Deterministic idempotency key — same signal within same UTC day → one order max.
    # Prevents duplicate orders if scheduler fires twice (e.g. coalesce miss or restart).
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    idem_key = idempotency_key_for_order(
        strategy_id=result.strategy_id,
        symbol=result.symbol,
        side=side.value,
        signal_id=today,
    )

    order = OrderRequest(
        symbol=result.symbol,
        exchange=ExchangeId.BINANCE,
        side=side,
        order_type=OrderType.MARKET,
        quantity=quantity,
        strategy_id=result.strategy_id,
        idempotency_key=idem_key,
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

    # ── Idempotency gate — block duplicate orders across restarts ────────────
    from trading_bot.idempotency.decorator import _default_store as _idem_store

    if _idem_store is not None:
        acquired = await _idem_store.acquire(idem_key)
        if not acquired:
            log.info(
                "router_idempotency_skip",
                strategy=result.strategy_id,
                symbol=result.symbol,
                side=side.value,
                key_prefix=idem_key[:8],
            )
            return

    # ── Execute on paper exchange ────────────────────────────────────────────
    signal_time = datetime.now(UTC)
    try:
        fill_resp = await _exchange.place_order(order)
        actual_price = Decimal(fill_resp["fill_price"])
        actual_filled_qty = Decimal(str(fill_resp.get("filled_quantity", order.quantity)))
        portfolio.apply_fill(order, actual_price)

        order_state = OrderState(
            client_order_id=order.client_order_id,
            exchange_order_id=fill_resp.get("exchange_order_id", ""),
            symbol=order.symbol,
            exchange=order.exchange,
            side=order.side,
            order_type=order.order_type,
            requested_quantity=order.quantity,
            filled_quantity=actual_filled_qty,
            average_fill_price=actual_price,
            status=OrderStatus.FILLED,
            strategy_id=order.strategy_id,
        )
        tracker.record(order_state)

        # ── TCA: record fill quality vs signal price ─────────────────────
        fill_latency_ms = (datetime.now(UTC) - signal_time).total_seconds() * 1000
        from trading_bot.tca.tracker import OrderOutcome, get_tca_tracker

        get_tca_tracker().record(
            order_id=order.client_order_id,
            symbol=order.symbol,
            side=order.side.value,
            signal_price=float(fill_price),
            fill_price=float(actual_price),
            quantity=float(actual_filled_qty),
            latency_ms=fill_latency_ms,
            outcome=OrderOutcome.FILLED,
        )

        # ── Accounting: record trade lot + FIFO PnL ───────────────────────
        from trading_bot.accounting.ledger import get_accounting_ledger

        fee_usdt = float(actual_filled_qty) * float(actual_price) * 0.001  # taker 0.1%
        get_accounting_ledger().record_trade(
            symbol=order.symbol,
            side=order.side.value,
            quantity=actual_filled_qty,
            price=actual_price,
            fee_usdt=fee_usdt,
            order_id=order.client_order_id,
        )

    except Exception as e:
        log.error("router_execution_error", error=str(e), symbol=order.symbol)


async def route_signals(results: list[StrategyResult]) -> None:
    """Route all strategy results. Called after each signal refresh."""
    for result in results:
        await route_signal(result)
