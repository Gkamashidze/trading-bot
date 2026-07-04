"""Unit tests for the operator-controlled micro-live executor.

The safety-critical property is that it FAILS CLOSED: no order reaches the
exchange unless the live flag is on AND the micro-live gate approves.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.execution.micro_live_executor import MicroLiveExecutor, MicroLiveRefusedError
from trading_bot.promotion.micro_live import MicroLiveGate


def _exchange() -> AsyncMock:
    ex = AsyncMock()
    ex.reference_price = AsyncMock(return_value=Decimal("50000"))
    ex.place_order = AsyncMock(
        return_value={
            "exchange_order_id": "T1",
            "fill_price": "50000",
            "filled_quantity": "0.0002",
            "status": "filled",
        }
    )
    return ex


def _allowing_gate() -> MagicMock:
    gate = MagicMock()
    gate.is_order_allowed.return_value = (True, "")
    return gate


class TestGating:
    @pytest.mark.asyncio
    async def test_refuses_when_flag_off(self) -> None:
        ex = _exchange()
        executor = MicroLiveExecutor(ex, _allowing_gate())
        with patch("trading_bot.feature_flags.is_enabled", AsyncMock(return_value=False)):
            with pytest.raises(MicroLiveRefusedError, match="live_trading_enabled"):
                await executor.submit(
                    symbol="BTC/USDT", side="BUY", usd_notional=10, operator="alice"
                )
        ex.place_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refuses_when_globally_disabled(self) -> None:
        # Flag on, but the real MicroLiveGate has _MICRO_LIVE_GLOBALLY_ENABLED = False.
        ex = _exchange()
        executor = MicroLiveExecutor(ex, MicroLiveGate())
        with (
            patch("trading_bot.feature_flags.is_enabled", AsyncMock(return_value=True)),
            patch(
                "trading_bot.portfolio.manager.get_portfolio_manager",
                return_value=MagicMock(
                    get_snapshot=MagicMock(return_value=MagicMock(positions=[]))
                ),
            ),
        ):
            with pytest.raises(MicroLiveRefusedError, match="globally disabled"):
                await executor.submit(
                    symbol="BTC/USDT", side="BUY", usd_notional=10, operator="alice"
                )
        ex.place_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refuses_when_gate_denies(self) -> None:
        ex = _exchange()
        gate = MagicMock()
        gate.is_order_allowed.return_value = (False, "order notional exceeds micro-live max")
        executor = MicroLiveExecutor(ex, gate)
        with (
            patch("trading_bot.feature_flags.is_enabled", AsyncMock(return_value=True)),
            patch(
                "trading_bot.portfolio.manager.get_portfolio_manager",
                return_value=MagicMock(
                    get_snapshot=MagicMock(return_value=MagicMock(positions=[]))
                ),
            ),
        ):
            with pytest.raises(MicroLiveRefusedError, match="exceeds micro-live max"):
                await executor.submit(
                    symbol="BTC/USDT", side="BUY", usd_notional=999, operator="alice"
                )
        ex.place_order.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_places_and_records_when_allowed(self) -> None:
        ex = _exchange()
        gate = _allowing_gate()
        executor = MicroLiveExecutor(ex, gate)

        portfolio = MagicMock(get_snapshot=MagicMock(return_value=MagicMock(positions=[])))
        lot = MagicMock(lot_id="L1")
        ledger = MagicMock(
            record_trade=MagicMock(return_value=lot), realized_for_sell=MagicMock(return_value=None)
        )

        with (
            patch("trading_bot.feature_flags.is_enabled", AsyncMock(return_value=True)),
            patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=portfolio),
            patch("trading_bot.oms.tracker.get_order_tracker", return_value=MagicMock()),
            patch("trading_bot.accounting.ledger.get_accounting_ledger", return_value=ledger),
            patch("trading_bot.evidence.recorder.record_fill_evidence", AsyncMock()) as rec_ev,
        ):
            fill = await executor.submit(
                symbol="BTC/USDT", side="BUY", usd_notional=10, operator="alice"
            )

        ex.place_order.assert_awaited_once()
        gate.record_fill.assert_called_once()
        rec_ev.assert_awaited_once()
        assert fill["status"] == "filled"
