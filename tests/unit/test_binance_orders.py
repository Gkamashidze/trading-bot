"""Unit tests for BinanceExchange real-order methods.

The CCXT client is mocked — no network. Verifies constraint quantization,
idempotent client order id, response parsing, and fail-closed rejection.
Order placement targets the configured endpoint (testnet in these tests).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from trading_bot.core.exceptions import OrderRejectedError
from trading_bot.core.models import ExchangeId, OrderRequest, OrderSide, OrderType
from trading_bot.exchange.binance import (
    BinanceExchange,
    _constraints_from_market,
    _parse_order_response,
)

_MARKET = {
    "symbol": "BTC/USDT",
    "base": "BTC",
    "quote": "USDT",
    "limits": {"amount": {"min": 0.00001, "max": 9000}, "cost": {"min": 10}},
    "precision": {"amount": 0.00001, "price": 0.01},
}


def _exchange_with_mock_client(create_order_return: dict | None = None) -> BinanceExchange:
    ex = BinanceExchange(testnet=True)
    client = AsyncMock()
    client.load_markets = AsyncMock(return_value={"BTC/USDT": _MARKET})
    client.fetch_ticker = AsyncMock(return_value={"last": 50000.0})
    client.create_order = AsyncMock(
        return_value=create_order_return
        or {
            "id": "999",
            "filled": 0.001,
            "average": 50010.0,
            "fee": {"cost": 0.05, "currency": "USDT"},
            "status": "closed",
        }
    )
    client.cancel_order = AsyncMock(return_value={"id": "999", "status": "canceled"})
    client.fetch_order = AsyncMock(return_value={"id": "999", "status": "closed"})
    client.last_response_headers = {}
    ex._client = client  # type: ignore[assignment]
    # Bypass the module-level rate-limit/circuit gate (other tests may trip it).
    ex._assert_request_allowed = lambda: None  # type: ignore[method-assign]
    return ex


def _order(qty: str, side: OrderSide = OrderSide.BUY) -> OrderRequest:
    return OrderRequest(
        client_order_id="test-order-123",
        symbol="BTC/USDT",
        exchange=ExchangeId.BINANCE,
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestConstraintsFromMarket:
    def test_builds_constraints(self) -> None:
        c = _constraints_from_market(_MARKET)
        assert c is not None
        assert c.qty_step == Decimal("0.00001")
        assert c.tick_size == Decimal("0.01")
        assert c.min_notional == Decimal("10")

    def test_none_for_empty_market(self) -> None:
        assert _constraints_from_market({}) is None


class TestParseOrderResponse:
    def test_full_fill(self) -> None:
        out = _parse_order_response(
            {"id": "1", "filled": 0.001, "average": 50010.0, "fee": {"cost": 0.05}},
            Decimal("0.001"),
        )
        assert out["status"] == "filled"
        assert out["exchange_order_id"] == "1"
        assert out["fill_price"] == "50010.0"
        assert out["fee_paid"] == "0.05"

    def test_partial_fill(self) -> None:
        out = _parse_order_response(
            {"id": "1", "filled": 0.0005, "average": 50000}, Decimal("0.001")
        )
        assert out["status"] == "partially_filled"


# ---------------------------------------------------------------------------
# place_order
# ---------------------------------------------------------------------------


class TestPlaceOrder:
    @pytest.mark.asyncio
    async def test_places_and_parses_fill(self) -> None:
        ex = _exchange_with_mock_client()
        result = await ex.place_order(_order("0.001"))
        assert result["status"] == "filled"
        assert result["exchange_order_id"] == "999"
        ex._client.create_order.assert_awaited_once()
        # idempotent client order id passed through as newClientOrderId
        params = ex._client.create_order.await_args.args[-1]
        assert params["newClientOrderId"] == "test-order-123"

    @pytest.mark.asyncio
    async def test_quantizes_quantity_to_lot_step(self) -> None:
        ex = _exchange_with_mock_client()
        await ex.place_order(_order("0.0012345"))  # → 0.00123 after 0.00001 step
        submitted_amount = ex._client.create_order.await_args.args[3]
        assert submitted_amount == pytest.approx(0.00123)

    @pytest.mark.asyncio
    async def test_rejects_below_min_notional(self) -> None:
        ex = _exchange_with_mock_client()
        # 0.00001 * 50000 = $0.50 < $10 min notional
        with pytest.raises(OrderRejectedError, match="min_notional"):
            await ex.place_order(_order("0.00001"))
        ex._client.create_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_and_status(self) -> None:
        ex = _exchange_with_mock_client()
        cancelled = await ex.cancel_order("999", "BTC/USDT")
        assert cancelled["status"] == "canceled"
        status = await ex.get_order_status("999", "BTC/USDT")
        assert status["status"] == "closed"
