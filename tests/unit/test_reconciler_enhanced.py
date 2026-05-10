"""Tests for enhanced reconciliation — balance checks, severity, order blocking."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.core.models import ExchangeId, OrderState, OrderStatus
from trading_bot.oms.reconciler import Reconciler, ReconciliationSeverity
from trading_bot.oms.tracker import OrderTracker
from trading_bot.utils.clock import FakeClock

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock(start=datetime(2024, 1, 1, tzinfo=UTC))


@pytest.fixture
def mock_exchange() -> AsyncMock:
    exchange = AsyncMock()
    exchange.fetch_open_orders.return_value = []
    exchange.fetch_balances.return_value = {"USDT": Decimal("10000")}
    return exchange


def _open_order(client_id: str = "abc", exchange_id: str | None = None) -> OrderState:
    return OrderState(
        client_order_id=client_id,
        exchange_order_id=exchange_id,
        symbol="BTC/USDT",
        exchange=ExchangeId.BINANCE,
        side="buy",
        order_type="market",
        requested_quantity=Decimal("0.01"),
        status=OrderStatus.OPEN,
    )


def _mock_portfolio(cash: Decimal = Decimal("10000")) -> MagicMock:
    snap = MagicMock()
    snap.cash_balance = cash
    manager = MagicMock()
    manager.get_snapshot.return_value = snap
    return manager


# ---------------------------------------------------------------------------
# Clean run tests
# ---------------------------------------------------------------------------


class TestCleanReconciliation:
    @pytest.mark.asyncio
    async def test_ok_severity_when_everything_matches(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock
    ) -> None:
        tracker = OrderTracker()
        with (
            patch("trading_bot.oms.reconciler.get_order_tracker", return_value=tracker),
            patch(
                "trading_bot.oms.reconciler.get_portfolio_manager",
                return_value=_mock_portfolio(Decimal("10000")),
            ),
        ):
            r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
            report = await r.run_once()

        assert report.severity == ReconciliationSeverity.OK
        assert report.order_discrepancies == []
        assert report.balance_discrepancies == []
        assert not report.orders_blocked

    @pytest.mark.asyncio
    async def test_run_count_increments(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock
    ) -> None:
        tracker = OrderTracker()
        with (
            patch("trading_bot.oms.reconciler.get_order_tracker", return_value=tracker),
            patch(
                "trading_bot.oms.reconciler.get_portfolio_manager",
                return_value=_mock_portfolio(),
            ),
        ):
            r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
            await r.run_once()
            await r.run_once()
        assert r.run_count == 2


# ---------------------------------------------------------------------------
# Balance discrepancy tests
# ---------------------------------------------------------------------------


class TestBalanceReconciliation:
    @pytest.mark.asyncio
    async def test_warning_on_small_balance_drift(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock
    ) -> None:
        # Exchange reports $10003, OMS has $10000 → $3 drift → warning
        mock_exchange.fetch_balances.return_value = {"USDT": Decimal("10003")}
        tracker = OrderTracker()
        with (
            patch("trading_bot.oms.reconciler.get_order_tracker", return_value=tracker),
            patch(
                "trading_bot.oms.reconciler.get_portfolio_manager",
                return_value=_mock_portfolio(Decimal("10000")),
            ),
        ):
            r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
            report = await r.run_once()

        assert len(report.balance_discrepancies) > 0
        assert report.severity in (ReconciliationSeverity.WARNING, ReconciliationSeverity.CRITICAL)

    @pytest.mark.asyncio
    async def test_critical_on_large_balance_drift(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock
    ) -> None:
        # Exchange reports $10500, OMS has $10000 → $500 drift → critical
        mock_exchange.fetch_balances.return_value = {"USDT": Decimal("10500")}
        tracker = OrderTracker()
        with (
            patch("trading_bot.oms.reconciler.get_order_tracker", return_value=tracker),
            patch(
                "trading_bot.oms.reconciler.get_portfolio_manager",
                return_value=_mock_portfolio(Decimal("10000")),
            ),
        ):
            r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
            report = await r.run_once()

        assert report.severity == ReconciliationSeverity.CRITICAL
        assert report.orders_blocked


# ---------------------------------------------------------------------------
# Orders blocked on critical mismatch
# ---------------------------------------------------------------------------


class TestOrderBlocking:
    @pytest.mark.asyncio
    async def test_orders_blocked_on_critical_mismatch(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock
    ) -> None:
        mock_exchange.fetch_balances.return_value = {"USDT": Decimal("9000")}
        tracker = OrderTracker()
        with (
            patch("trading_bot.oms.reconciler.get_order_tracker", return_value=tracker),
            patch(
                "trading_bot.oms.reconciler.get_portfolio_manager",
                return_value=_mock_portfolio(Decimal("10000")),
            ),
        ):
            r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
            assert not r.orders_blocked
            await r.run_once()
            assert r.orders_blocked

    @pytest.mark.asyncio
    async def test_clear_block_resumes_orders(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock
    ) -> None:
        mock_exchange.fetch_balances.return_value = {"USDT": Decimal("9000")}
        tracker = OrderTracker()
        with (
            patch("trading_bot.oms.reconciler.get_order_tracker", return_value=tracker),
            patch(
                "trading_bot.oms.reconciler.get_portfolio_manager",
                return_value=_mock_portfolio(Decimal("10000")),
            ),
        ):
            r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
            await r.run_once()
            assert r.orders_blocked
            r.clear_block()
            assert not r.orders_blocked

    @pytest.mark.asyncio
    async def test_auto_clear_on_clean_run_after_block(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock
    ) -> None:
        tracker = OrderTracker()
        with (
            patch("trading_bot.oms.reconciler.get_order_tracker", return_value=tracker),
            patch(
                "trading_bot.oms.reconciler.get_portfolio_manager",
                return_value=_mock_portfolio(Decimal("10000")),
            ),
        ):
            r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
            # First: trigger critical block
            mock_exchange.fetch_balances.return_value = {"USDT": Decimal("9000")}
            await r.run_once()
            assert r.orders_blocked
            # Second: clean run → block auto-cleared
            mock_exchange.fetch_balances.return_value = {"USDT": Decimal("10000")}
            await r.run_once()
            assert not r.orders_blocked


# ---------------------------------------------------------------------------
# Ghost order detection → critical severity
# ---------------------------------------------------------------------------


class TestGhostOrderDetection:
    @pytest.mark.asyncio
    async def test_ghost_order_is_critical(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock
    ) -> None:
        # OMS has an order with exchange_order_id, but exchange doesn't know about it
        tracker = OrderTracker()
        tracker.record(_open_order("o1", exchange_id="EX-999"))
        mock_exchange.fetch_open_orders.return_value = []  # exchange: empty

        with (
            patch("trading_bot.oms.reconciler.get_order_tracker", return_value=tracker),
            patch(
                "trading_bot.oms.reconciler.get_portfolio_manager",
                return_value=_mock_portfolio(Decimal("10000")),
            ),
        ):
            r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
            report = await r.run_once()

        assert report.severity == ReconciliationSeverity.CRITICAL
        assert any("ghost" in d for d in report.order_discrepancies)


# ---------------------------------------------------------------------------
# Backward compatibility — run_once_as_event
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_run_once_as_event_returns_reconciliation_event(
        self, mock_exchange: AsyncMock, fake_clock: FakeClock
    ) -> None:
        from trading_bot.core.events import ReconciliationEvent

        tracker = OrderTracker()
        with (
            patch("trading_bot.oms.reconciler.get_order_tracker", return_value=tracker),
            patch(
                "trading_bot.oms.reconciler.get_portfolio_manager",
                return_value=_mock_portfolio(),
            ),
        ):
            r = Reconciler(mock_exchange, ExchangeId.BINANCE, clock=fake_clock)
            event = await r.run_once_as_event()

        assert isinstance(event, ReconciliationEvent)
        assert event.matched is True
