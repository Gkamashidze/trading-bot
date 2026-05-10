"""Unit tests for extended operator controls (Feature #13)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.risk.capital_policy import (
    CapitalPolicyEngine,
    StrategyAllocationState,
)


class TestCapitalPolicyStateManagement:
    """Tests for the new set_strategy_state / get_strategy_state API."""

    def test_default_state_is_active(self) -> None:
        engine = CapitalPolicyEngine()
        assert engine.get_strategy_state("any_id") == StrategyAllocationState.ACTIVE

    def test_set_paused(self) -> None:
        engine = CapitalPolicyEngine()
        engine.set_strategy_state("s1", StrategyAllocationState.PAUSED)
        assert engine.get_strategy_state("s1") == StrategyAllocationState.PAUSED

    def test_set_reduced_risk(self) -> None:
        engine = CapitalPolicyEngine()
        engine.set_strategy_state("s1", StrategyAllocationState.REDUCED_RISK)
        assert engine.get_strategy_state("s1") == StrategyAllocationState.REDUCED_RISK

    def test_resume_after_pause(self) -> None:
        engine = CapitalPolicyEngine()
        engine.set_strategy_state("s1", StrategyAllocationState.PAUSED)
        engine.set_strategy_state("s1", StrategyAllocationState.ACTIVE)
        assert engine.get_strategy_state("s1") == StrategyAllocationState.ACTIVE

    def test_set_state_idempotent(self) -> None:
        engine = CapitalPolicyEngine()
        engine.set_strategy_state("s1", StrategyAllocationState.PAUSED)
        engine.set_strategy_state("s1", StrategyAllocationState.PAUSED)
        assert engine.get_strategy_state("s1") == StrategyAllocationState.PAUSED

    def test_runtime_paused_blocks_order(self) -> None:
        from decimal import Decimal

        from trading_bot.core.models import (
            AssetClass,
            ExchangeId,
            OrderRequest,
            OrderSide,
            PortfolioSnapshot,
        )
        from trading_bot.risk.capital_policy import CapitalPolicyConfig

        engine = CapitalPolicyEngine(CapitalPolicyConfig())
        engine.set_strategy_state("my_strat", StrategyAllocationState.PAUSED)

        order = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=Decimal("0.01"),
            exchange=ExchangeId.BINANCE,
            strategy_id="my_strat",
        )
        snap = PortfolioSnapshot(
            cash_balance=Decimal("10000"),
            positions=[],
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("0"),
            daily_drawdown_pct=Decimal("0"),
        )
        decision = engine.check(order, snap, AssetClass.CRYPTO)
        assert not decision.approved
        assert "paused" in decision.reason.lower()

    def test_runtime_state_overrides_config_state(self) -> None:
        """Engine configured ACTIVE but runtime set to PAUSED → order blocked."""
        from decimal import Decimal

        from trading_bot.core.models import (
            AssetClass,
            ExchangeId,
            OrderRequest,
            OrderSide,
            PortfolioSnapshot,
        )
        from trading_bot.risk.capital_policy import (
            CapitalPolicyConfig,
            StrategyPolicy,
        )

        cfg = CapitalPolicyConfig(
            strategy_policies={
                "s1": StrategyPolicy(
                    strategy_id="s1",
                    max_capital_pct=0.5,
                    state=StrategyAllocationState.ACTIVE,
                )
            }
        )
        engine = CapitalPolicyEngine(cfg)
        engine.set_strategy_state("s1", StrategyAllocationState.PAUSED)

        order = OrderRequest(
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type="market",
            quantity=Decimal("0.01"),
            exchange=ExchangeId.BINANCE,
            strategy_id="s1",
        )
        snap = PortfolioSnapshot(
            cash_balance=Decimal("10000"),
            positions=[],
            total_equity=Decimal("10000"),
            daily_pnl=Decimal("0"),
            daily_drawdown_pct=Decimal("0"),
        )
        decision = engine.check(order, snap, AssetClass.CRYPTO)
        assert not decision.approved


class TestTelegramCommandHandler:
    """Tests for the extended Telegram operator commands."""

    def _make_handler(self) -> object:
        from trading_bot.operator_console.telegram_commands import TelegramCommandHandler

        return TelegramCommandHandler(
            token="fake_token",
            authorized_chat_id=123456,
            pool=None,
        )

    @pytest.mark.asyncio
    async def test_pause_command_sets_paused_state(self) -> None:
        handler = self._make_handler()
        client = AsyncMock()
        mock_engine = MagicMock()

        # Lazy import inside _cmd_pause — patch at source module
        with patch(
            "trading_bot.risk.capital_policy.get_capital_policy_engine", return_value=mock_engine
        ):
            from trading_bot.operator_console.telegram_commands import TelegramCommandHandler

            await TelegramCommandHandler._cmd_pause(handler, client, 123456, ["sma_v1"])  # type: ignore[arg-type]

        mock_engine.set_strategy_state.assert_called_once_with(
            "sma_v1", StrategyAllocationState.PAUSED
        )

    @pytest.mark.asyncio
    async def test_resume_command_sets_active_state(self) -> None:
        handler = self._make_handler()
        client = AsyncMock()
        mock_engine = MagicMock()

        with patch(
            "trading_bot.risk.capital_policy.get_capital_policy_engine", return_value=mock_engine
        ):
            from trading_bot.operator_console.telegram_commands import TelegramCommandHandler

            await TelegramCommandHandler._cmd_resume(handler, client, 123456, ["sma_v1"])  # type: ignore[arg-type]

        mock_engine.set_strategy_state.assert_called_once_with(
            "sma_v1", StrategyAllocationState.ACTIVE
        )

    @pytest.mark.asyncio
    async def test_reduce_risk_command(self) -> None:
        handler = self._make_handler()
        client = AsyncMock()
        mock_engine = MagicMock()

        with patch(
            "trading_bot.risk.capital_policy.get_capital_policy_engine", return_value=mock_engine
        ):
            from trading_bot.operator_console.telegram_commands import TelegramCommandHandler

            await TelegramCommandHandler._cmd_reduce_risk(handler, client, 123456, ["s1"])  # type: ignore[arg-type]

        mock_engine.set_strategy_state.assert_called_once_with(
            "s1", StrategyAllocationState.REDUCED_RISK
        )

    @pytest.mark.asyncio
    async def test_pause_missing_arg_sends_error(self) -> None:
        handler = self._make_handler()
        client = AsyncMock()

        with patch.object(type(handler), "_send", new_callable=AsyncMock) as mock_send:
            from trading_bot.operator_console.telegram_commands import TelegramCommandHandler

            await TelegramCommandHandler._cmd_pause(handler, client, 123456, [])  # type: ignore[arg-type]

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][2]
        assert "გამოყენება" in sent_text or "pause" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_ack_command_acknowledges_alert(self) -> None:
        handler = self._make_handler()
        client = AsyncMock()

        from trading_bot.monitoring.slo import SLIName, SLOMonitor

        monitor = SLOMonitor()
        alert = monitor.record(SLIName.WEBSOCKET_FRESHNESS, 200.0)
        assert alert is not None

        # Lazy import inside _cmd_ack — patch at source module
        with patch("trading_bot.monitoring.slo.get_slo_monitor", return_value=monitor):
            with patch.object(type(handler), "_send", new_callable=AsyncMock):
                from trading_bot.operator_console.telegram_commands import TelegramCommandHandler

                await TelegramCommandHandler._cmd_ack(handler, client, 123456, [alert.alert_id])  # type: ignore[arg-type]

        assert monitor.active_alerts()[0].acknowledged is True

    @pytest.mark.asyncio
    async def test_ack_unknown_alert_sends_error(self) -> None:
        handler = self._make_handler()
        client = AsyncMock()

        mock_monitor = MagicMock()
        mock_monitor.acknowledge.side_effect = KeyError("not found")

        with patch("trading_bot.monitoring.slo.get_slo_monitor", return_value=mock_monitor):
            with patch.object(type(handler), "_send", new_callable=AsyncMock) as mock_send:
                from trading_bot.operator_console.telegram_commands import TelegramCommandHandler

                await TelegramCommandHandler._cmd_ack(  # type: ignore[arg-type]
                    handler, client, 123456, ["bad-alert-id"]
                )

        mock_send.assert_called_once()
        assert "ვერ მოიძებნა" in mock_send.call_args[0][2]

    @pytest.mark.asyncio
    async def test_dispatch_unknown_command_sends_help_hint(self) -> None:
        handler = self._make_handler()
        client = AsyncMock()

        with patch.object(type(handler), "_send", new_callable=AsyncMock) as mock_send:
            from trading_bot.operator_console.telegram_commands import TelegramCommandHandler

            await TelegramCommandHandler._dispatch(  # type: ignore[arg-type]
                handler, client, 123456, "nonexistent", []
            )

        mock_send.assert_called_once()
        assert "/help" in mock_send.call_args[0][2]
