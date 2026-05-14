"""Unit tests for Stage 5: Risk Engine, Portfolio Manager, OMS Tracker, Paper Exchange."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from trading_bot.core.models import (
    AssetClass,
    ExchangeId,
    OrderRequest,
    OrderSide,
    OrderState,
    OrderStatus,
    OrderType,
    PortfolioSnapshot,
    Position,
)
from trading_bot.oms.tracker import OrderTracker
from trading_bot.portfolio.manager import PortfolioManager
from trading_bot.risk.engine import RiskDecision, RiskEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_snapshot(
    cash: float = 10_000.0,
    equity: float = 10_000.0,
    daily_dd: float = 0.0,
) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash_balance=Decimal(str(cash)),
        positions=[],
        total_equity=Decimal(str(equity)),
        daily_pnl=Decimal("0"),
        daily_drawdown_pct=Decimal(str(daily_dd)),
    )


def _buy_order(
    symbol: str = "BTC/USDT",
    quantity: float = 0.1,
    strategy_id: str = "test",
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        exchange=ExchangeId.BINANCE,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal(str(quantity)),
        strategy_id=strategy_id,
    )


def _sell_order(symbol: str = "BTC/USDT", quantity: float = 0.1) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        exchange=ExchangeId.BINANCE,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal(str(quantity)),
    )


# ---------------------------------------------------------------------------
# RiskEngine
# ---------------------------------------------------------------------------


class TestRiskEngine:
    def setup_method(self) -> None:
        self.engine = RiskEngine()

    def test_approve_normal_buy(self) -> None:
        snap = _empty_snapshot()
        order = _buy_order(quantity=0.01)  # $300 of ~$30k BTC → well within limits
        decision = self.engine.pre_trade_check(order, snap, Decimal("30000"))
        assert decision.approved
        assert decision.reason == ""
        assert decision.tier == 0

    def test_reject_zero_equity(self) -> None:
        snap = _empty_snapshot(cash=0, equity=0)
        order = _buy_order()
        decision = self.engine.pre_trade_check(order, snap, Decimal("30000"))
        assert not decision.approved

    def test_reject_tier1_drawdown(self) -> None:
        snap = _empty_snapshot(daily_dd=-0.06)  # 6% > tier1 (5%)
        order = _buy_order()
        decision = self.engine.pre_trade_check(order, snap, Decimal("30000"))
        assert not decision.approved
        assert decision.tier == 1

    def test_reject_tier2_drawdown(self) -> None:
        snap = _empty_snapshot(daily_dd=-0.11)
        order = _buy_order()
        decision = self.engine.pre_trade_check(order, snap, Decimal("30000"))
        assert not decision.approved
        assert decision.tier == 2

    def test_reject_tier3_drawdown(self) -> None:
        snap = _empty_snapshot(daily_dd=-0.16)
        order = _buy_order()
        decision = self.engine.pre_trade_check(order, snap, Decimal("30000"))
        assert not decision.approved
        assert decision.tier == 3

    def test_reject_cash_floor_breach(self) -> None:
        # Cash = $1000, equity = $10000, floor = 10% = $1000
        # Buying $200 worth → cash after = $800 < floor $1000
        snap = _empty_snapshot(cash=1000, equity=10_000)
        order = _buy_order(quantity=0.01)  # 0.01 BTC x $20000 = $200
        decision = self.engine.pre_trade_check(order, snap, Decimal("20000"))
        assert not decision.approved
        assert "cash floor" in decision.reason

    def test_reject_concentration_limit(self) -> None:
        # Existing BTC position = $3500, equity = $10000, limit = 30% = $3000
        existing_pos = Position(
            symbol="BTC/USDT",
            exchange=ExchangeId.BINANCE,
            asset_class=AssetClass.CRYPTO,
            quantity=Decimal("0.1"),
            average_cost=Decimal("35000"),
            current_price=Decimal("35000"),
            opened_at=datetime.now(UTC),
        )
        snap = PortfolioSnapshot(
            cash_balance=Decimal("6500"),
            positions=[existing_pos],
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("0"),
            daily_drawdown_pct=Decimal("0"),
        )
        # Buying another $1000 → total $4500 = 45% > 30% limit
        order = _buy_order(quantity=Decimal("0.0286"))  # ≈ $1001 at $35000
        decision = self.engine.pre_trade_check(order, snap, Decimal("35000"))
        assert not decision.approved
        assert "concentration" in decision.reason

    def test_sell_order_bypasses_buy_checks(self) -> None:
        # Drawdown is fine, selling should be allowed
        snap = _empty_snapshot()
        order = _sell_order(quantity=0.01)
        decision = self.engine.pre_trade_check(order, snap, Decimal("30000"))
        assert decision.approved

    def test_decision_is_frozen(self) -> None:
        snap = _empty_snapshot()
        order = _buy_order()
        decision = self.engine.pre_trade_check(order, snap, Decimal("30000"))
        assert isinstance(decision, RiskDecision)
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.approved = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PortfolioManager
# ---------------------------------------------------------------------------


class TestPortfolioManager:
    def _manager(self, capital: float = 10_000.0) -> PortfolioManager:
        return PortfolioManager(initial_capital=Decimal(str(capital)))

    def test_initial_snapshot(self) -> None:
        pm = self._manager()
        snap = pm.get_snapshot()
        assert snap.total_equity == Decimal("10000")
        assert snap.cash_balance == Decimal("10000")
        assert snap.positions == []
        assert snap.daily_pnl == Decimal("0")

    def test_buy_creates_position(self) -> None:
        pm = self._manager()
        order = _buy_order(quantity=0.1)
        pm.apply_fill(order, Decimal("50000"))
        snap = pm.get_snapshot()
        assert len(snap.positions) == 1
        pos = snap.positions[0]
        assert pos.quantity == Decimal("0.1")
        assert pos.average_cost == Decimal("50000")

    def test_buy_deducts_cash_with_fee(self) -> None:
        pm = self._manager(capital=10_000.0)
        order = _buy_order(quantity=0.1)
        fill_price = Decimal("50000")
        pm.apply_fill(order, fill_price, fee_rate=Decimal("0.001"))
        # cost = 0.1 * 50000 * 1.001 = 5005
        expected_cash = Decimal("10000") - Decimal("5005")
        assert pm.get_snapshot().cash_balance == expected_cash

    def test_buy_then_sell_closes_position(self) -> None:
        pm = self._manager()
        buy = _buy_order(quantity=0.1)
        pm.apply_fill(buy, Decimal("50000"), fee_rate=Decimal("0"))
        sell = _sell_order(quantity=0.1)
        pm.apply_fill(sell, Decimal("55000"), fee_rate=Decimal("0"))
        snap = pm.get_snapshot()
        assert len(snap.positions) == 0

    def test_sell_increases_cash(self) -> None:
        pm = self._manager()
        pm.apply_fill(_buy_order(quantity=0.1), Decimal("50000"), fee_rate=Decimal("0"))
        cash_after_buy = pm.get_snapshot().cash_balance
        pm.apply_fill(_sell_order(quantity=0.1), Decimal("55000"), fee_rate=Decimal("0"))
        cash_after_sell = pm.get_snapshot().cash_balance
        assert cash_after_sell > cash_after_buy

    def test_average_cost_updates_on_add_to_position(self) -> None:
        pm = self._manager()
        pm.apply_fill(_buy_order(quantity=0.1), Decimal("50000"), fee_rate=Decimal("0"))
        pm.apply_fill(_buy_order(quantity=0.1), Decimal("60000"), fee_rate=Decimal("0"))
        pos = pm.get_snapshot().positions[0]
        assert pos.average_cost == Decimal("55000")
        assert pos.quantity == Decimal("0.2")

    def test_update_prices_marks_to_market(self) -> None:
        pm = self._manager()
        pm.apply_fill(_buy_order(quantity=0.1), Decimal("50000"), fee_rate=Decimal("0"))
        pm.update_prices({"BTC/USDT": Decimal("60000")})
        pos = pm.get_snapshot().positions[0]
        assert pos.current_price == Decimal("60000")

    def test_daily_pnl_reflects_price_change(self) -> None:
        pm = self._manager(capital=10_000)
        pm.apply_fill(_buy_order(quantity=0.1), Decimal("50000"), fee_rate=Decimal("0"))
        pm.update_prices({"BTC/USDT": Decimal("60000")})
        snap = pm.get_snapshot()
        # Started with $10k, now position worth $6k + cash $5k = $11k → +$1k P&L
        assert snap.daily_pnl > 0

    def test_reset_day_updates_baseline(self) -> None:
        pm = self._manager()
        pm.apply_fill(_buy_order(quantity=0.1), Decimal("50000"), fee_rate=Decimal("0"))
        pm.update_prices({"BTC/USDT": Decimal("55000")})
        pm.reset_day()
        # After reset, daily P&L should be zero (new baseline = current equity)
        snap = pm.get_snapshot()
        assert snap.daily_pnl == Decimal("0")


# ---------------------------------------------------------------------------
# OrderTracker
# ---------------------------------------------------------------------------


class TestOrderTracker:
    def _filled_order(self) -> OrderState:
        return OrderState(
            client_order_id="test-123",
            symbol="BTC/USDT",
            exchange=ExchangeId.BINANCE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            requested_quantity=Decimal("0.1"),
            filled_quantity=Decimal("0.1"),
            average_fill_price=Decimal("50000"),
            status=OrderStatus.FILLED,
        )

    def test_record_and_retrieve(self) -> None:
        tracker = OrderTracker()
        order = self._filled_order()
        tracker.record(order)
        recent = tracker.recent(10)
        assert len(recent) == 1
        assert recent[0].client_order_id == "test-123"

    def test_recent_returns_newest_first(self) -> None:
        tracker = OrderTracker()
        for i in range(5):
            order = OrderState(
                client_order_id=f"order-{i}",
                symbol="BTC/USDT",
                exchange=ExchangeId.BINANCE,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                requested_quantity=Decimal("0.1"),
                status=OrderStatus.FILLED,
            )
            tracker.record(order)
        recent = tracker.recent(3)
        assert len(recent) == 3
        assert recent[0].client_order_id == "order-4"

    def test_max_capacity_respected(self) -> None:
        tracker = OrderTracker(max_orders=5)
        for i in range(10):
            order = OrderState(
                client_order_id=f"order-{i}",
                symbol="BTC/USDT",
                exchange=ExchangeId.BINANCE,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                requested_quantity=Decimal("0.1"),
                status=OrderStatus.FILLED,
            )
            tracker.record(order)
        assert tracker.count() == 5

    def test_count_tracks_total(self) -> None:
        tracker = OrderTracker()
        assert tracker.count() == 0
        tracker.record(self._filled_order())
        assert tracker.count() == 1


# ---------------------------------------------------------------------------
# PaperExchange
# ---------------------------------------------------------------------------


class TestPaperExchange:
    @pytest.mark.asyncio
    async def test_place_order_fills_at_ws_price(self) -> None:
        from trading_bot.core.models import PriceTick
        from trading_bot.execution.paper import PaperExchange

        tick = PriceTick(
            symbol="BTCUSDT",
            price=Decimal("50000"),
            open_24h=Decimal("48000"),
            high_24h=Decimal("51000"),
            low_24h=Decimal("47000"),
            volume_24h=Decimal("1000"),
            timestamp=datetime.now(UTC),
        )
        with patch("trading_bot.execution.paper.get_price_cache") as mock_cache:
            mock_cache.return_value.get.return_value = tick
            exchange = PaperExchange()
            order = _buy_order(quantity=0.1)
            result = await exchange.place_order(order)

        assert "fill_price" in result
        fill = Decimal(result["fill_price"])
        # BUY → price + slippage (0.05%) → > $50000
        assert fill > Decimal("50000")
        # Partial fill is valid — assert order executed (not rejected)
        assert result["status"] in ("filled", "partially_filled")

    @pytest.mark.asyncio
    async def test_place_order_no_price_raises(self) -> None:
        from trading_bot.core.exceptions import OrderRejectedError
        from trading_bot.execution.paper import PaperExchange

        with patch("trading_bot.execution.paper.get_price_cache") as mock_cache:
            mock_cache.return_value.get.return_value = None
            exchange = PaperExchange()
            order = _buy_order()
            with pytest.raises(OrderRejectedError):
                await exchange.place_order(order)

    @pytest.mark.asyncio
    async def test_sell_fill_price_below_market(self) -> None:
        from trading_bot.core.models import PriceTick
        from trading_bot.execution.paper import PaperExchange

        tick = PriceTick(
            symbol="BTCUSDT",
            price=Decimal("50000"),
            open_24h=Decimal("48000"),
            high_24h=Decimal("51000"),
            low_24h=Decimal("47000"),
            volume_24h=Decimal("1000"),
            timestamp=datetime.now(UTC),
        )
        with patch("trading_bot.execution.paper.get_price_cache") as mock_cache:
            mock_cache.return_value.get.return_value = tick
            exchange = PaperExchange()
            order = _sell_order(quantity=0.1)
            result = await exchange.place_order(order)

        fill = Decimal(result["fill_price"])
        # SELL fill = price - slippage, so < $50000
        assert fill < Decimal("50000")

    @pytest.mark.asyncio
    async def test_health_check_always_true(self) -> None:
        from trading_bot.execution.paper import PaperExchange

        exchange = PaperExchange()
        assert await exchange.health_check() is True

    @pytest.mark.asyncio
    async def test_fetch_balances_returns_cash(self) -> None:
        from trading_bot.execution.paper import PaperExchange

        pm = PortfolioManager(initial_capital=Decimal("5000"))
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            exchange = PaperExchange()
            balances = await exchange.fetch_balances()
        assert "USDT" in balances
        assert balances["USDT"] == Decimal("5000")
