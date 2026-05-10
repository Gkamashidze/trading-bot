"""Unit tests for capital allocation policy engine."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trading_bot.core.models import (
    AssetClass,
    ExchangeId,
    OrderRequest,
    OrderSide,
    OrderType,
    PortfolioSnapshot,
    Position,
)
from trading_bot.risk.capital_policy import (
    AssetClassPolicy,
    CapitalPolicyConfig,
    CapitalPolicyEngine,
    StrategyAllocationState,
    StrategyPolicy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snapshot(
    cash: Decimal = Decimal("10000"),
    positions: list[Position] | None = None,
    daily_pnl: Decimal = Decimal("0"),
) -> PortfolioSnapshot:
    pos = positions or []
    total = cash + sum(p.market_value for p in pos)
    return PortfolioSnapshot(
        cash_balance=cash,
        positions=pos,
        total_equity=total,
        daily_pnl=daily_pnl,
        daily_drawdown_pct=Decimal("0"),
    )


def _buy_order(
    symbol: str = "BTC/USDT",
    qty: Decimal = Decimal("0.1"),
    limit_price: Decimal = Decimal("50000"),
    strategy_id: str = "sma_crossover",
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        exchange=ExchangeId.BINANCE,
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=qty,
        limit_price=limit_price,
        strategy_id=strategy_id,
    )


def _sell_order(symbol: str = "BTC/USDT") -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        exchange=ExchangeId.BINANCE,
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
    )


def _position(
    symbol: str,
    qty: Decimal,
    price: Decimal,
    strategy_id: str = "sma_crossover",
    asset_class: AssetClass = AssetClass.CRYPTO,
) -> Position:
    return Position(
        symbol=symbol,
        exchange=ExchangeId.BINANCE,
        asset_class=asset_class,
        quantity=qty,
        average_cost=price,
        current_price=price,
        opened_at=datetime.now(UTC),
        strategy_id=strategy_id,
    )


# ---------------------------------------------------------------------------
# Sell orders are never blocked by capital policy
# ---------------------------------------------------------------------------


class TestSellOrdersPassThrough:
    def test_sell_always_approved(self) -> None:
        engine = CapitalPolicyEngine()
        snap = _snapshot(cash=Decimal("0"), daily_pnl=Decimal("-999"))
        decision = engine.check(_sell_order(), snap, AssetClass.CRYPTO, weekly_pnl_pct=-0.99)
        assert decision.approved
        assert "sell" in decision.reason


# ---------------------------------------------------------------------------
# Daily loss budget
# ---------------------------------------------------------------------------


class TestDailyLossBudget:
    def test_blocks_when_daily_loss_exceeds_budget(self) -> None:
        config = CapitalPolicyConfig(daily_loss_budget_pct=0.03)
        engine = CapitalPolicyEngine(config)
        # 3% daily loss on $10k equity = $300 loss
        snap = _snapshot(cash=Decimal("9700"), daily_pnl=Decimal("-300"))
        decision = engine.check(_buy_order(), snap, AssetClass.CRYPTO)
        assert not decision.approved
        assert "daily loss budget" in decision.reason

    def test_passes_when_daily_loss_below_budget(self) -> None:
        config = CapitalPolicyConfig(daily_loss_budget_pct=0.05)
        engine = CapitalPolicyEngine(config)
        snap = _snapshot(cash=Decimal("9900"), daily_pnl=Decimal("-100"))
        decision = engine.check(
            _buy_order(qty=Decimal("0.01"), limit_price=Decimal("10000")),
            snap,
            AssetClass.CRYPTO,
        )
        assert decision.approved

    def test_positive_daily_pnl_never_blocks(self) -> None:
        config = CapitalPolicyConfig(daily_loss_budget_pct=0.01)
        engine = CapitalPolicyEngine(config)
        snap = _snapshot(cash=Decimal("10000"), daily_pnl=Decimal("500"))
        decision = engine.check(
            _buy_order(qty=Decimal("0.001"), limit_price=Decimal("10000")),
            snap,
            AssetClass.CRYPTO,
        )
        assert decision.approved


# ---------------------------------------------------------------------------
# Weekly loss budget
# ---------------------------------------------------------------------------


class TestWeeklyLossBudget:
    def test_blocks_on_weekly_loss_exceeded(self) -> None:
        config = CapitalPolicyConfig(weekly_loss_budget_pct=0.07)
        engine = CapitalPolicyEngine(config)
        snap = _snapshot()
        decision = engine.check(
            _buy_order(qty=Decimal("0.001"), limit_price=Decimal("10000")),
            snap,
            AssetClass.CRYPTO,
            weekly_pnl_pct=-0.08,  # 8% loss > 7% budget
        )
        assert not decision.approved
        assert "weekly" in decision.reason

    def test_passes_within_weekly_budget(self) -> None:
        config = CapitalPolicyConfig(weekly_loss_budget_pct=0.07)
        engine = CapitalPolicyEngine(config)
        snap = _snapshot()
        decision = engine.check(
            _buy_order(qty=Decimal("0.001"), limit_price=Decimal("10000")),
            snap,
            AssetClass.CRYPTO,
            weekly_pnl_pct=-0.05,
        )
        assert decision.approved


# ---------------------------------------------------------------------------
# Strategy-level caps
# ---------------------------------------------------------------------------


class TestStrategyCapitalCap:
    def test_blocks_when_strategy_exceeds_cap(self) -> None:
        config = CapitalPolicyConfig(max_capital_per_strategy_pct=0.20)
        engine = CapitalPolicyEngine(config)

        # Existing strategy position = $2000 on $10k equity = 20%
        pos = _position("BTC/USDT", Decimal("0.04"), Decimal("50000"))
        snap = _snapshot(cash=Decimal("8000"), positions=[pos])

        # New order would push to 25%
        decision = engine.check(
            _buy_order(qty=Decimal("0.001"), limit_price=Decimal("50000")),
            snap,
            AssetClass.CRYPTO,
        )
        assert not decision.approved
        assert "strategy" in decision.reason.lower()
        assert "cap" in decision.reason.lower()

    def test_passes_within_strategy_cap(self) -> None:
        config = CapitalPolicyConfig(max_capital_per_strategy_pct=0.30)
        engine = CapitalPolicyEngine(config)
        snap = _snapshot(cash=Decimal("9000"))
        # Order value = 0.001 * 50000 = $50 = 0.5% of equity — well within 30%
        decision = engine.check(
            _buy_order(qty=Decimal("0.001"), limit_price=Decimal("50000")),
            snap,
            AssetClass.CRYPTO,
        )
        assert decision.approved


# ---------------------------------------------------------------------------
# PAUSED strategy
# ---------------------------------------------------------------------------


class TestPausedStrategy:
    def test_paused_strategy_blocks_all_new_entries(self) -> None:
        policy = StrategyPolicy(
            strategy_id="sma_crossover",
            max_capital_pct=0.30,
            state=StrategyAllocationState.PAUSED,
        )
        config = CapitalPolicyConfig(strategy_policies={"sma_crossover": policy})
        engine = CapitalPolicyEngine(config)
        snap = _snapshot()
        decision = engine.check(_buy_order(), snap, AssetClass.CRYPTO)
        assert not decision.approved
        assert "paused" in decision.reason

    def test_active_strategy_not_blocked(self) -> None:
        policy = StrategyPolicy(
            strategy_id="sma_crossover",
            max_capital_pct=0.30,
            state=StrategyAllocationState.ACTIVE,
        )
        config = CapitalPolicyConfig(strategy_policies={"sma_crossover": policy})
        engine = CapitalPolicyEngine(config)
        snap = _snapshot()
        decision = engine.check(
            _buy_order(qty=Decimal("0.001"), limit_price=Decimal("50000")),
            snap,
            AssetClass.CRYPTO,
        )
        assert decision.approved


# ---------------------------------------------------------------------------
# Per-asset cap
# ---------------------------------------------------------------------------


class TestPerAssetCap:
    def test_blocks_when_asset_exceeds_cap(self) -> None:
        config = CapitalPolicyConfig(max_capital_per_asset_pct=0.20)
        engine = CapitalPolicyEngine(config)

        # BTC position = $2000 on $10k equity = 20%
        pos = _position("BTC/USDT", Decimal("0.04"), Decimal("50000"))
        snap = _snapshot(cash=Decimal("8000"), positions=[pos])

        # Any new BTC buy would exceed 20%
        decision = engine.check(
            _buy_order("BTC/USDT", qty=Decimal("0.001"), limit_price=Decimal("50000")),
            snap,
            AssetClass.CRYPTO,
        )
        assert not decision.approved
        assert "BTC/USDT" in decision.reason

    def test_different_asset_not_affected(self) -> None:
        # Per-asset cap: 20%. Asset-class cap raised to 60% so CRYPTO class
        # doesn't trigger before per-asset logic is the binding constraint.
        config = CapitalPolicyConfig(
            max_capital_per_asset_pct=0.20,
            asset_class_policies={
                str(AssetClass.CRYPTO): AssetClassPolicy(
                    asset_class=AssetClass.CRYPTO, max_capital_pct=0.60
                )
            },
        )
        engine = CapitalPolicyEngine(config)

        # BTC at 20% but buying ETH ($30 order) — per-asset cap not breached
        pos = _position("BTC/USDT", Decimal("0.04"), Decimal("50000"))
        snap = _snapshot(cash=Decimal("8000"), positions=[pos])

        decision = engine.check(
            _buy_order("ETH/USDT", qty=Decimal("0.01"), limit_price=Decimal("3000")),
            snap,
            AssetClass.CRYPTO,
        )
        assert decision.approved


# ---------------------------------------------------------------------------
# Zero / negative equity
# ---------------------------------------------------------------------------


class TestZeroEquity:
    def test_zero_equity_blocks(self) -> None:
        engine = CapitalPolicyEngine()
        snap = PortfolioSnapshot(
            cash_balance=Decimal("0"),
            positions=[],
            total_equity=Decimal("0"),
            daily_pnl=Decimal("0"),
            daily_drawdown_pct=Decimal("0"),
        )
        decision = engine.check(_buy_order(), snap, AssetClass.CRYPTO)
        assert not decision.approved
        assert "zero" in decision.reason
