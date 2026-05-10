"""Tests for FakeExchangeAdapter."""

from decimal import Decimal

import pytest

from trading_bot.core.exceptions import OrderRejectedError
from trading_bot.core.models import ExchangeId, OrderRequest, OrderSide, OrderType
from trading_bot.exchange.fake_exchange import FakeExchangeAdapter, FakeFillConfig


def _order(
    symbol: str = "BTC/USDT",
    side: OrderSide = OrderSide.BUY,
    qty: str = "0.001",
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        exchange=ExchangeId.BINANCE,
        side=side,
        order_type=OrderType.MARKET,
        quantity=Decimal(qty),
        strategy_id="test_strategy",
    )


class TestFakeExchangeAdapter:
    def setup_method(self) -> None:
        self.exchange = FakeExchangeAdapter(initial_balance={"USDT": Decimal("10000")})
        self.exchange.inject_price("BTC/USDT", Decimal("50000"))

    @pytest.mark.asyncio
    async def test_place_order_full_fill(self) -> None:
        result = await self.exchange.place_order(_order())
        assert result["status"] == "filled"
        assert Decimal(result["filled_quantity"]) == Decimal("0.001")
        assert len(self.exchange.placed_orders) == 1

    @pytest.mark.asyncio
    async def test_place_order_partial_fill(self) -> None:
        self.exchange.inject_fill_config("BTC/USDT", FakeFillConfig(fill_pct=0.5))
        result = await self.exchange.place_order(_order())
        assert result["status"] == "partially_filled"
        assert Decimal(result["filled_quantity"]) == Decimal("0.0005")

    @pytest.mark.asyncio
    async def test_place_order_rejected(self) -> None:
        self.exchange.inject_fill_config(
            "BTC/USDT", FakeFillConfig(reject=True, reject_reason="test_reject")
        )
        with pytest.raises(OrderRejectedError, match="test_reject"):
            await self.exchange.place_order(_order())
        assert self.exchange.placed_orders[-1].status == "rejected"

    @pytest.mark.asyncio
    async def test_cancel_order(self) -> None:
        result = await self.exchange.place_order(_order())
        eid = result["exchange_order_id"]
        await self.exchange.cancel_order(eid, "BTC/USDT")
        assert eid in self.exchange.cancelled_order_ids

    @pytest.mark.asyncio
    async def test_replace_order(self) -> None:
        result = await self.exchange.place_order(_order())
        old_eid = result["exchange_order_id"]
        replace_result = await self.exchange.replace_order(
            old_eid, "BTC/USDT", new_qty=Decimal("0.002")
        )
        assert replace_result["original_order_id"] == old_eid
        assert old_eid in self.exchange.cancelled_order_ids

    @pytest.mark.asyncio
    async def test_fetch_balances(self) -> None:
        balances = await self.exchange.fetch_balances()
        assert balances["USDT"] == Decimal("10000")

    @pytest.mark.asyncio
    async def test_health_check_healthy(self) -> None:
        assert await self.exchange.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self) -> None:
        self.exchange.set_healthy(False)
        assert await self.exchange.health_check() is False

    @pytest.mark.asyncio
    async def test_call_tracking(self) -> None:
        await self.exchange.place_order(_order())
        await self.exchange.place_order(_order())
        assert self.exchange.call_count("place_order") == 2
        assert self.exchange.call_count("cancel_order") == 0

    @pytest.mark.asyncio
    async def test_slippage_applied_on_buy(self) -> None:
        self.exchange.inject_fill_config("BTC/USDT", FakeFillConfig(slippage_bps=10.0))
        result = await self.exchange.place_order(_order(side=OrderSide.BUY))
        fill_price = Decimal(result["fill_price"])
        assert fill_price > Decimal("50000")

    @pytest.mark.asyncio
    async def test_server_time_returns_utc(self) -> None:
        t = await self.exchange.get_server_time()
        assert t.tzinfo is not None
