"""Unit tests for execution/router.py — order routing logic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from trading_bot.core.models import (
    OrderStatus,
    PortfolioSnapshot,
)
from trading_bot.strategies.base import StrategyResult


def _snapshot(cash: float = 10_000.0) -> PortfolioSnapshot:
    return PortfolioSnapshot(
        cash_balance=Decimal(str(cash)),
        positions=[],
        total_equity=Decimal(str(cash)),
        daily_pnl=Decimal("0"),
        daily_drawdown_pct=Decimal("0"),
    )


def _result(signal: str = "BUY", strategy_id: str = "sma_crossover") -> StrategyResult:
    return StrategyResult(
        strategy_id=strategy_id,
        symbol="BTC/USDT",
        signal=signal,
        strength=0.8,
        indicators={"sma_20": 50000.0, "sma_50": 48000.0},
        bars_used=100,
        computed_at=datetime.now(UTC),
    )


class TestRouterHoldSignal:
    async def test_hold_signal_does_nothing(self) -> None:
        from trading_bot.execution.router import route_signal

        # is_enabled and get_circuit_breaker are lazy-imported inside route_signal —
        # patch them at their source modules.
        with (
            patch("trading_bot.feature_flags.is_enabled", new=AsyncMock(return_value=True)),
            patch("trading_bot.safety.circuit_breaker.get_circuit_breaker") as mock_cb,
        ):
            mock_cb.return_value.is_trading_allowed.return_value = True
            tracker = MagicMock()
            portfolio = MagicMock()
            portfolio.get_snapshot.return_value = _snapshot()

            with (
                patch("trading_bot.execution.router.get_order_tracker", return_value=tracker),
                patch("trading_bot.execution.router.get_portfolio_manager", return_value=portfolio),
            ):
                await route_signal(_result(signal="HOLD"))

        tracker.record.assert_not_called()


class TestRouterKillSwitch:
    async def test_kill_switch_disables_routing(self) -> None:
        from trading_bot.execution.router import route_signal

        with patch("trading_bot.feature_flags.is_enabled", new=AsyncMock(return_value=False)):
            tracker = MagicMock()
            with patch("trading_bot.execution.router.get_order_tracker", return_value=tracker):
                await route_signal(_result(signal="BUY"))

        tracker.record.assert_not_called()


class TestRouterCircuitBreaker:
    async def test_circuit_breaker_halt_blocks_order(self) -> None:
        from trading_bot.execution.router import route_signal

        with (
            patch("trading_bot.feature_flags.is_enabled", new=AsyncMock(return_value=True)),
            patch("trading_bot.safety.circuit_breaker.get_circuit_breaker") as mock_cb,
        ):
            mock_cb.return_value.is_trading_allowed.return_value = False
            mock_cb.return_value.current_tier = 2
            mock_cb.return_value.last_drawdown_pct = 0.11

            tracker = MagicMock()
            with patch("trading_bot.execution.router.get_order_tracker", return_value=tracker):
                await route_signal(_result(signal="BUY"))

        tracker.record.assert_not_called()


class TestRouterRiskRejection:
    async def test_risk_rejected_order_is_recorded_as_rejected(self) -> None:
        from trading_bot.execution.router import _last_signal, route_signal
        from trading_bot.risk.engine import RiskDecision

        # Clear signal state to ensure fresh signal
        _last_signal.clear()

        mock_decision = RiskDecision(approved=False, reason="drawdown_limit", tier=1)

        with (
            patch("trading_bot.feature_flags.is_enabled", new=AsyncMock(return_value=True)),
            patch("trading_bot.safety.circuit_breaker.get_circuit_breaker") as mock_cb,
            patch("trading_bot.execution.router._risk") as mock_risk,
            patch("trading_bot.websocket.price_cache.get_price_cache") as mock_cache,
        ):
            mock_cb.return_value.is_trading_allowed.return_value = True
            mock_risk.pre_trade_check.return_value = mock_decision
            mock_tick = MagicMock()
            mock_tick.price = Decimal("50000")
            mock_cache.return_value.get.return_value = mock_tick

            tracker = MagicMock()
            portfolio = MagicMock()
            portfolio.get_snapshot.return_value = _snapshot()

            with (
                patch("trading_bot.execution.router.get_order_tracker", return_value=tracker),
                patch("trading_bot.execution.router.get_portfolio_manager", return_value=portfolio),
                patch("trading_bot.idempotency.decorator._default_store", None),
            ):
                await route_signal(_result(signal="BUY"))

        tracker.record.assert_called_once()
        call_args = tracker.record.call_args[0][0]
        assert call_args.status == OrderStatus.REJECTED


class TestRouterIdempotencyKey:
    def test_deterministic_idempotency_key_same_day(self) -> None:
        from trading_bot.idempotency.keys import idempotency_key_for_order

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        key1 = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        key2 = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        assert key1 == key2

    def test_different_signals_produce_different_keys(self) -> None:
        from trading_bot.idempotency.keys import idempotency_key_for_order

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        buy_key = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        sell_key = idempotency_key_for_order("sma_crossover", "BTC/USDT", "sell", today)
        assert buy_key != sell_key

    def test_different_strategies_produce_different_keys(self) -> None:
        from trading_bot.idempotency.keys import idempotency_key_for_order

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        key_sma = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        key_rsi = idempotency_key_for_order("rsi_mean_reversion", "BTC/USDT", "buy", today)
        assert key_sma != key_rsi
