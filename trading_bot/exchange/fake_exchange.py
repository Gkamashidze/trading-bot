"""FakeExchangeAdapter — deterministic test double for ExchangeInterface.

Designed for unit and integration tests that need a fully functional exchange
without any real network calls or credentials. Supports:

- place_order with configurable fill simulation (instant, partial, reject)
- cancel_order and replace_order
- order book snapshots (injected per test)
- fetch_balances, fetch_open_orders, fetch_ohlcv
- symbol constraints injection for precision validator tests
- call history for assertion

Usage in tests:
    fake = FakeExchangeAdapter(initial_balance={"USDT": Decimal("10000")})
    fake.inject_price("BTC/USDT", Decimal("50000"))
    result = await fake.place_order(order_request)
    assert fake.placed_orders[-1].symbol == "BTC/USDT"
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trading_bot.core.contracts import ExchangeInterface
from trading_bot.core.models import OrderRequest, OrderSide
from trading_bot.exchange.precision import SymbolConstraints


@dataclass
class FakeFillConfig:
    """Controls how FakeExchangeAdapter simulates fills."""

    fill_pct: float = 1.0  # 1.0 = full fill, 0.5 = 50% partial
    reject: bool = False
    reject_reason: str = ""
    slippage_bps: float = 0.0  # basis points added to price


@dataclass
class FakeOrderRecord:
    """Record of an order placed against the fake exchange."""

    exchange_order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    requested_qty: Decimal
    filled_qty: Decimal
    fill_price: Decimal
    status: str  # "filled" | "partially_filled" | "rejected" | "cancelled" | "open"
    placed_at: datetime
    cancelled_at: datetime | None = None
    replace_count: int = 0


class FakeExchangeAdapter(ExchangeInterface):
    """Fully in-memory exchange adapter for testing.

    Thread-safety: NOT thread-safe. Use one instance per test.
    """

    def __init__(
        self,
        initial_balance: dict[str, Decimal] | None = None,
        server_time: datetime | None = None,
        maker_fee: Decimal = Decimal("0.001"),
        taker_fee: Decimal = Decimal("0.001"),
    ) -> None:
        self._balance: dict[str, Decimal] = initial_balance or {"USDT": Decimal("10000")}
        self._server_time = server_time or datetime.now(UTC)
        self._maker_fee = maker_fee
        self._taker_fee = taker_fee

        self._prices: dict[str, Decimal] = {}
        self._fill_configs: dict[str, FakeFillConfig] = {}  # keyed by symbol
        self._default_fill = FakeFillConfig()
        self._symbol_constraints: dict[str, SymbolConstraints] = {}

        self._open_orders: dict[str, FakeOrderRecord] = {}  # exchange_order_id → record
        self._placed_orders: list[FakeOrderRecord] = []
        self._cancelled_order_ids: list[str] = []
        self._replaced_order_ids: list[tuple[str, str]] = []  # (old, new)

        self._healthy = True
        self._call_count: dict[str, int] = {}

    # ── Test helpers ────────────────────────────────────────────────────────

    def inject_price(self, symbol: str, price: Decimal) -> None:
        self._prices[symbol] = price

    def inject_fill_config(self, symbol: str, config: FakeFillConfig) -> None:
        self._fill_configs[symbol] = config

    def inject_constraints(self, symbol: str, constraints: SymbolConstraints) -> None:
        self._symbol_constraints[symbol] = constraints

    def set_healthy(self, healthy: bool) -> None:
        self._healthy = healthy

    @property
    def placed_orders(self) -> list[FakeOrderRecord]:
        return list(self._placed_orders)

    @property
    def cancelled_order_ids(self) -> list[str]:
        return list(self._cancelled_order_ids)

    # ── ExchangeInterface ────────────────────────────────────────────────────

    async def place_order(self, order: Any) -> dict[str, Any]:
        self._track("place_order")
        req: OrderRequest = order

        fill_cfg = self._fill_configs.get(req.symbol, self._default_fill)

        if fill_cfg.reject:
            reason = fill_cfg.reject_reason or "fake_exchange_reject"
            record = FakeOrderRecord(
                exchange_order_id=f"FAKE-REJ-{uuid.uuid4().hex[:8]}",
                client_order_id=req.client_order_id,
                symbol=req.symbol,
                side=req.side,
                requested_qty=req.quantity,
                filled_qty=Decimal("0"),
                fill_price=Decimal("0"),
                status="rejected",
                placed_at=datetime.now(UTC),
            )
            self._placed_orders.append(record)
            from trading_bot.core.exceptions import OrderRejectedError

            raise OrderRejectedError(reason)

        ref_price = self._prices.get(req.symbol, Decimal("100"))
        slippage = Decimal(str(fill_cfg.slippage_bps)) / Decimal("10000")
        if req.side == OrderSide.BUY:
            fill_price = ref_price * (Decimal("1") + slippage)
        else:
            fill_price = ref_price * (Decimal("1") - slippage)

        filled_qty = req.quantity * Decimal(str(fill_cfg.fill_pct))
        is_partial = fill_cfg.fill_pct < 1.0
        status = "partially_filled" if is_partial else "filled"
        eid = f"FAKE-{uuid.uuid4().hex[:12].upper()}"

        record = FakeOrderRecord(
            exchange_order_id=eid,
            client_order_id=req.client_order_id,
            symbol=req.symbol,
            side=req.side,
            requested_qty=req.quantity,
            filled_qty=filled_qty,
            fill_price=fill_price,
            status=status,
            placed_at=datetime.now(UTC),
        )
        self._placed_orders.append(record)
        if is_partial:
            self._open_orders[eid] = record

        fee = filled_qty * fill_price * self._taker_fee
        return {
            "exchange_order_id": eid,
            "fill_price": str(fill_price),
            "filled_quantity": str(filled_qty),
            "fee_paid": str(fee),
            "slippage_cost": str(filled_qty * ref_price * slippage),
            "status": status,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def cancel_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]:
        self._track("cancel_order")
        self._cancelled_order_ids.append(exchange_order_id)
        if exchange_order_id in self._open_orders:
            record = self._open_orders.pop(exchange_order_id)
            object.__setattr__(record, "status", "cancelled")  # dataclass not frozen
            record.cancelled_at = datetime.now(UTC)
        return {"exchange_order_id": exchange_order_id, "status": "cancelled"}

    async def replace_order(
        self,
        exchange_order_id: str,
        symbol: str,
        new_qty: Decimal | None = None,
        new_price: Decimal | None = None,
    ) -> dict[str, Any]:
        """Cancel old order and place a replacement. Returns new order dict."""
        self._track("replace_order")
        await self.cancel_order(exchange_order_id, symbol)

        # Build a minimal replacement request
        ref_price = new_price or self._prices.get(symbol, Decimal("100"))
        qty = new_qty or Decimal("1")
        new_eid = f"FAKE-RPL-{uuid.uuid4().hex[:10].upper()}"
        self._replaced_order_ids.append((exchange_order_id, new_eid))
        return {
            "exchange_order_id": new_eid,
            "original_order_id": exchange_order_id,
            "fill_price": str(ref_price),
            "filled_quantity": str(qty),
            "status": "open",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: Any = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        self._track("fetch_ohlcv")
        price = self._prices.get(symbol, Decimal("100"))
        now = datetime.now(UTC)
        return [
            {
                "open_time": now,
                "open": price,
                "high": price * Decimal("1.01"),
                "low": price * Decimal("0.99"),
                "close": price,
                "volume": Decimal("1000"),
                "quote_volume": price * Decimal("1000"),
                "trade_count": 500,
                "close_time": now,
            }
        ]

    async def fetch_balances(self) -> dict[str, Decimal]:
        self._track("fetch_balances")
        return dict(self._balance)

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        self._track("fetch_open_orders")
        orders = list(self._open_orders.values())
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return [
            {
                "exchange_order_id": o.exchange_order_id,
                "symbol": o.symbol,
                "side": o.side,
                "qty": str(o.requested_qty),
                "status": o.status,
            }
            for o in orders
        ]

    async def fetch_trade_fees(self, symbol: str) -> dict[str, Decimal]:
        return {"maker": self._maker_fee, "taker": self._taker_fee}

    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        self._track("get_symbol_info")
        constraints = self._symbol_constraints.get(symbol)
        if constraints is None:
            return {}
        return {
            "symbol": symbol,
            "min_qty": str(constraints.min_qty),
            "max_qty": str(constraints.max_qty),
            "qty_step": str(constraints.qty_step),
            "tick_size": str(constraints.tick_size),
            "min_notional": str(constraints.min_notional),
        }

    async def get_server_time(self) -> datetime:
        return self._server_time

    async def health_check(self) -> bool:
        return self._healthy

    def _track(self, method: str) -> None:
        self._call_count[method] = self._call_count.get(method, 0) + 1

    def call_count(self, method: str) -> int:
        return self._call_count.get(method, 0)
