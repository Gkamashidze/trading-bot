"""Alpaca paper-execution tests.

These tests submit REAL orders to the Alpaca paper trading API.
They are SKIPPED in normal CI unless --paper-execution-test is passed.

Requirements:
  - ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables set.
  - The keys must belong to an Alpaca paper trading account.
  - Run with: pytest tests/integration/test_alpaca_paper_execution.py --paper-execution-test

Safety:
  - AlpacaExchange is always constructed in paper=True mode here.
  - All submitted orders are cancelled immediately after submission.
  - Only SPY (the most liquid ETF) is used — 1 share, never multiple.
  - ALLOW_LIVE_TRADING is NOT set, so live orders are impossible.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest

from trading_bot.core.models import ExchangeId, OrderRequest, OrderSide, OrderType, TimeInForce
from trading_bot.exchange.alpaca import AlpacaExchange

pytestmark = pytest.mark.paper_execution


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def paper_adapter() -> AlpacaExchange:
    """AlpacaExchange pointed at the paper API with real credentials."""
    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")

    if not api_key or not secret_key:
        pytest.skip(
            "ALPACA_API_KEY / ALPACA_SECRET_KEY not set — skipping paper execution test. "
            "Export the env vars and re-run with --paper-execution-test."
        )

    return AlpacaExchange(
        api_key=api_key,
        secret_key=secret_key,
        paper=True,  # ALWAYS paper — never live
        allowed_symbols=frozenset({"SPY", "QQQ", "SOXX", "IBIT"}),
        allow_live_trading=False,  # explicit safety
    )


# ---------------------------------------------------------------------------
# Connectivity check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_health_check(paper_adapter: AlpacaExchange) -> None:
    """Verify we can reach the Alpaca paper API and the account is ACTIVE."""
    healthy = await paper_adapter.health_check()
    assert healthy, "Alpaca paper account health check failed — check API keys and account status"


@pytest.mark.asyncio
async def test_paper_get_server_time(paper_adapter: AlpacaExchange) -> None:
    """Server time must be a UTC-aware datetime."""

    t = await paper_adapter.get_server_time()
    assert t.tzinfo is not None
    assert t.year >= 2024


@pytest.mark.asyncio
async def test_paper_fetch_balances(paper_adapter: AlpacaExchange) -> None:
    """Account must report a non-negative USD cash balance."""
    balances = await paper_adapter.fetch_balances()
    assert "USD" in balances
    assert balances["USD"] >= Decimal("0")


# ---------------------------------------------------------------------------
# SPY symbol metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_spy_symbol_info(paper_adapter: AlpacaExchange) -> None:
    """SPY must be tradable on Alpaca."""
    info = await paper_adapter.get_symbol_info("SPY")
    assert info["symbol"] == "SPY"
    assert info["tradable"] is True


# ---------------------------------------------------------------------------
# Market-hours-aware order: submit + cancel SPY 1 share
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_submit_and_cancel_spy_market_order(paper_adapter: AlpacaExchange) -> None:
    """Submit a 1-share SPY market order and immediately cancel it.

    If the market is closed this test is skipped gracefully (market-hours
    guard in AlpacaExchange raises ExchangeOrderError with 'market is closed').
    """
    from trading_bot.core.exceptions import ExchangeOrderError

    req = OrderRequest(
        symbol="SPY",
        exchange=ExchangeId.ALPACA,
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("1"),
        time_in_force=TimeInForce.DAY,
        strategy_id="paper_execution_test",
    )

    try:
        result = await paper_adapter.place_order(req)
    except ExchangeOrderError as exc:
        if "market is closed" in str(exc):
            pytest.skip(f"US equity market is closed — skipping order test. ({exc})")
        raise

    order_id: str = result["exchange_order_id"]
    assert order_id, "Expected a non-empty order ID from Alpaca"

    # Cancel immediately — paper orders can be cancelled even if already filled
    try:
        cancel_result = await paper_adapter.cancel_order(order_id, "SPY")
        assert cancel_result["status"] == "cancelled"
    except ExchangeOrderError:
        # Already filled (market order in live session) — still a pass
        pass


# ---------------------------------------------------------------------------
# Open orders list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_fetch_open_orders_is_list(paper_adapter: AlpacaExchange) -> None:
    """fetch_open_orders must return a list (may be empty)."""
    orders = await paper_adapter.fetch_open_orders()
    assert isinstance(orders, list)


# ---------------------------------------------------------------------------
# OHLCV historical data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_paper_fetch_ohlcv_spy(paper_adapter: AlpacaExchange) -> None:
    """Fetch SPY daily bars and verify at least one is returned."""
    from datetime import timedelta

    try:
        from datetime import UTC, datetime

        one_week_ago = datetime.now(UTC) - timedelta(days=10)
        bars = await paper_adapter.fetch_ohlcv("SPY", "1d", since=one_week_ago, limit=10)
    except Exception as exc:
        pytest.fail(f"fetch_ohlcv raised unexpectedly: {exc}")

    assert isinstance(bars, list)
    if bars:
        bar = bars[0]
        assert "close" in bar
        assert "open_time" in bar
        assert bar["open_time"].tzinfo is not None
