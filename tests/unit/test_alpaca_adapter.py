"""Unit tests for the AlpacaExchange adapter.

All tests use mocked alpaca-py clients (no real network calls).
The _trading and _data_client attributes are replaced with MagicMock instances
after adapter construction, which itself is patched to skip HTTP auth.

mypy note: adapter._trading and adapter._data_client are typed as SDK classes.
Use _t(adapter) / _d(adapter) helpers to cast to MagicMock for test assertions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from trading_bot.core.exceptions import (
    ExchangeAuthError,
    ExchangeOrderError,
    KillSwitchError,
)
from trading_bot.core.models import ExchangeId, OrderRequest, OrderSide, OrderType, TimeInForce
from trading_bot.exchange.alpaca import _PAPER_BASE_URL, AlpacaExchange

# ---------------------------------------------------------------------------
# Typed cast helpers — avoid weakening production types, satisfy mypy in tests
# ---------------------------------------------------------------------------


def _t(adapter: AlpacaExchange) -> MagicMock:
    """Return the mocked TradingClient for assertions."""
    return cast(MagicMock, adapter._trading)


def _d(adapter: AlpacaExchange) -> MagicMock:
    """Return the mocked StockHistoricalDataClient for assertions."""
    return cast(MagicMock, adapter._data_client)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _fake_order_result(
    order_id: str = "test-order-id",
    status: str = "accepted",
    fill_price: str | None = None,
    filled_qty: str | None = None,
) -> MagicMock:
    mock = MagicMock()
    mock.id = uuid.UUID(order_id) if len(order_id) == 36 else uuid.uuid4()
    mock.status.value = status
    mock.filled_avg_price = fill_price
    mock.filled_qty = filled_qty
    mock.created_at = datetime.now(UTC)
    return mock


def _fake_account(cash: str = "10000.00", portfolio_value: str = "12000.00") -> MagicMock:
    mock = MagicMock()
    mock.cash = cash
    mock.portfolio_value = portfolio_value
    mock.equity = portfolio_value
    mock.last_equity = "11800.00"
    mock.buying_power = "20000.00"
    mock.status.value = "ACTIVE"
    return mock


def _fake_clock(is_open: bool = True) -> MagicMock:
    mock = MagicMock()
    mock.is_open = is_open
    mock.timestamp = datetime.now(UTC)
    return mock


def _make_order_request(
    symbol: str = "SPY",
    side: OrderSide = OrderSide.BUY,
    qty: str = "1",
    order_type: OrderType = OrderType.MARKET,
    limit_price: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        exchange=ExchangeId.ALPACA,
        side=side,
        order_type=order_type,
        quantity=Decimal(qty),
        limit_price=Decimal(limit_price) if limit_price else None,
        time_in_force=TimeInForce.DAY,
    )


def _fake_barset(symbol: str, bars: list[MagicMock]) -> MagicMock:
    """Return a BarSet-like mock that exposes .data — matching real alpaca-py behaviour."""
    mock = MagicMock()
    mock.data = {symbol.upper(): bars}
    return mock


@pytest.fixture
def alpaca() -> AlpacaExchange:
    """AlpacaExchange with mocked Alpaca SDK clients (no real HTTP)."""
    with (
        patch("trading_bot.exchange.alpaca.TradingClient"),
        patch("trading_bot.exchange.alpaca.StockHistoricalDataClient"),
    ):
        adapter = AlpacaExchange(
            api_key="test-key",
            secret_key="test-secret",
            paper=True,
            allowed_symbols=frozenset({"SPY", "QQQ", "SOXX", "IBIT"}),
        )
    # Replace with fresh mocks so tests control behaviour directly
    adapter._trading = MagicMock()
    adapter._data_client = MagicMock()
    return adapter


# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_paper_mode_default_succeeds(self) -> None:
        with (
            patch("trading_bot.exchange.alpaca.TradingClient"),
            patch("trading_bot.exchange.alpaca.StockHistoricalDataClient"),
        ):
            adapter = AlpacaExchange(paper=True)
        assert adapter._paper is True

    def test_live_mode_without_allow_flag_raises(self) -> None:
        with pytest.raises(KillSwitchError, match="ALLOW_LIVE_TRADING"):
            AlpacaExchange(paper=False, allow_live_trading=False)

    def test_live_mode_with_allow_flag_succeeds(self) -> None:
        with (
            patch("trading_bot.exchange.alpaca.TradingClient"),
            patch("trading_bot.exchange.alpaca.StockHistoricalDataClient"),
        ):
            adapter = AlpacaExchange(paper=False, allow_live_trading=True)
        assert adapter._paper is False

    def test_allowed_symbols_uppercased(self) -> None:
        with (
            patch("trading_bot.exchange.alpaca.TradingClient"),
            patch("trading_bot.exchange.alpaca.StockHistoricalDataClient"),
        ):
            adapter = AlpacaExchange(allowed_symbols=frozenset({"spy", "qqq"}))
        assert "SPY" in adapter._allowed_symbols
        assert "QQQ" in adapter._allowed_symbols

    def test_ibit_in_default_allowlist(self) -> None:
        """IBIT is an equity ETF (iShares Bitcoin Trust), not a crypto symbol."""
        with (
            patch("trading_bot.exchange.alpaca.TradingClient"),
            patch("trading_bot.exchange.alpaca.StockHistoricalDataClient"),
        ):
            adapter = AlpacaExchange()
        assert "IBIT" in adapter._allowed_symbols

    def test_trading_client_receives_url_override(self) -> None:
        custom_url = "https://custom.alpaca.markets"
        with (
            patch("trading_bot.exchange.alpaca.TradingClient") as mock_tc,
            patch("trading_bot.exchange.alpaca.StockHistoricalDataClient"),
        ):
            AlpacaExchange(paper=True, trading_base_url=custom_url)

        call_kwargs: dict[str, Any] = dict(mock_tc.call_args.kwargs)
        assert call_kwargs.get("url_override") == custom_url

    def test_default_trading_url_is_paper_endpoint(self) -> None:
        with (
            patch("trading_bot.exchange.alpaca.TradingClient") as mock_tc,
            patch("trading_bot.exchange.alpaca.StockHistoricalDataClient"),
        ):
            AlpacaExchange(paper=True)

        call_kwargs: dict[str, Any] = dict(mock_tc.call_args.kwargs)
        assert call_kwargs.get("url_override") == _PAPER_BASE_URL

    def test_data_client_does_not_receive_trading_url(self) -> None:
        """Data API uses its own endpoint — trading URL must not be forwarded."""
        with (
            patch("trading_bot.exchange.alpaca.TradingClient"),
            patch("trading_bot.exchange.alpaca.StockHistoricalDataClient") as mock_dc,
        ):
            AlpacaExchange(paper=True, trading_base_url="https://trading.example.com")

        call_kwargs: dict[str, Any] = dict(mock_dc.call_args.kwargs)
        assert "url_override" not in call_kwargs or call_kwargs.get("url_override") is None


# ---------------------------------------------------------------------------
# Symbol allowlist enforcement
# ---------------------------------------------------------------------------


class TestSymbolAllowlist:
    async def test_order_outside_allowlist_raises(self, alpaca: AlpacaExchange) -> None:
        req = _make_order_request(symbol="TSLA")
        with pytest.raises(ExchangeOrderError, match="not in the Alpaca ETF allowlist"):
            await alpaca.place_order(req)

    async def test_order_in_allowlist_proceeds(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_clock.return_value = _fake_clock(is_open=True)
        _t(alpaca).submit_order.return_value = _fake_order_result()

        result = await alpaca.place_order(_make_order_request(symbol="SPY"))
        assert "exchange_order_id" in result

    async def test_ibit_order_accepted_as_equity(self, alpaca: AlpacaExchange) -> None:
        """IBIT must be treated as a US equity by the allowlist, not blocked as crypto."""
        _t(alpaca).get_clock.return_value = _fake_clock(is_open=True)
        _t(alpaca).submit_order.return_value = _fake_order_result()

        result = await alpaca.place_order(_make_order_request(symbol="IBIT"))
        assert "exchange_order_id" in result


# ---------------------------------------------------------------------------
# Market-hours guard
# ---------------------------------------------------------------------------


class TestMarketHoursGuard:
    async def test_order_when_market_closed_raises(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_clock.return_value = _fake_clock(is_open=False)

        with pytest.raises(ExchangeOrderError, match="market is closed"):
            await alpaca.place_order(_make_order_request())

    async def test_order_when_market_open_proceeds(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_clock.return_value = _fake_clock(is_open=True)
        _t(alpaca).submit_order.return_value = _fake_order_result()

        result = await alpaca.place_order(_make_order_request())
        assert result["status"] == "accepted"


# ---------------------------------------------------------------------------
# Order placement
# ---------------------------------------------------------------------------


class TestPlaceOrder:
    async def test_market_buy_returns_order_dict(self, alpaca: AlpacaExchange) -> None:
        oid = str(uuid.uuid4())
        _t(alpaca).get_clock.return_value = _fake_clock(is_open=True)
        _t(alpaca).submit_order.return_value = _fake_order_result(order_id=oid)

        result = await alpaca.place_order(_make_order_request(side=OrderSide.BUY))
        assert result["exchange_order_id"] == oid
        assert result["fee_paid"] == "0"  # commission-free

    async def test_market_sell_submits_sell_side(self, alpaca: AlpacaExchange) -> None:
        from alpaca.trading.enums import OrderSide as ASide

        _t(alpaca).get_clock.return_value = _fake_clock(is_open=True)
        _t(alpaca).submit_order.return_value = _fake_order_result()

        await alpaca.place_order(_make_order_request(side=OrderSide.SELL))
        submitted: Any = _t(alpaca).submit_order.call_args[0][0]
        assert submitted.side == ASide.SELL

    async def test_limit_order_includes_limit_price(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_clock.return_value = _fake_clock(is_open=True)
        _t(alpaca).submit_order.return_value = _fake_order_result()

        await alpaca.place_order(
            _make_order_request(order_type=OrderType.LIMIT, limit_price="450.00")
        )
        submitted: Any = _t(alpaca).submit_order.call_args[0][0]
        assert abs(submitted.limit_price - 450.00) < 0.01

    async def test_unsupported_order_type_raises(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_clock.return_value = _fake_clock(is_open=True)

        req = OrderRequest(
            symbol="SPY",
            exchange=ExchangeId.ALPACA,
            side=OrderSide.BUY,
            order_type=OrderType.STOP,
            quantity=Decimal("1"),
            stop_price=Decimal("430"),
        )
        with pytest.raises(ExchangeOrderError, match="not supported"):
            await alpaca.place_order(req)

    async def test_alpaca_api_error_raises_exchange_order_error(
        self, alpaca: AlpacaExchange
    ) -> None:
        _t(alpaca).get_clock.return_value = _fake_clock(is_open=True)
        _t(alpaca).submit_order.side_effect = RuntimeError("something went wrong")

        with pytest.raises(ExchangeOrderError):
            await alpaca.place_order(_make_order_request())

    async def test_auth_error_surfaces_as_exchange_auth_error(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_clock.return_value = _fake_clock(is_open=True)
        _t(alpaca).submit_order.side_effect = RuntimeError("403 forbidden")

        with pytest.raises(ExchangeAuthError):
            await alpaca.place_order(_make_order_request())


# ---------------------------------------------------------------------------
# Cancel order
# ---------------------------------------------------------------------------


class TestCancelOrder:
    async def test_cancel_calls_alpaca_cancel(self, alpaca: AlpacaExchange) -> None:
        oid = str(uuid.uuid4())
        _t(alpaca).cancel_order_by_id.return_value = None

        result = await alpaca.cancel_order(oid, "SPY")
        assert result["status"] == "cancelled"
        assert result["exchange_order_id"] == oid
        _t(alpaca).cancel_order_by_id.assert_called_once()


# ---------------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------------


class TestFetchBalances:
    async def test_returns_usd_and_portfolio_value(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_account.return_value = _fake_account("9500.50", "11200.75")

        balances = await alpaca.fetch_balances()
        assert balances["USD"] == Decimal("9500.50")
        assert balances["portfolio_value"] == Decimal("11200.75")


# ---------------------------------------------------------------------------
# OHLCV — BarSet.data fix regression tests
# ---------------------------------------------------------------------------


class TestFetchOHLCV:
    def _make_bar(self, price: float = 450.0) -> MagicMock:
        bar = MagicMock()
        bar.timestamp = datetime.now(UTC)
        bar.open = price
        bar.high = price * 1.005
        bar.low = price * 0.995
        bar.close = price
        bar.volume = 1_000_000.0
        bar.trade_count = 50_000
        return bar

    async def test_uses_barset_data_attribute_not_get(self, alpaca: AlpacaExchange) -> None:
        """Regression: alpaca-py returns BarSet with .data, not a plain dict with .get()."""
        fake_bar = self._make_bar(450.0)
        _d(alpaca).get_stock_bars.return_value = _fake_barset("SPY", [fake_bar])

        bars = await alpaca.fetch_ohlcv("SPY", "1d", limit=1)
        assert len(bars) == 1

    async def test_returns_decimal_prices(self, alpaca: AlpacaExchange) -> None:
        fake_bar = self._make_bar(450.0)
        _d(alpaca).get_stock_bars.return_value = _fake_barset("SPY", [fake_bar])

        bars = await alpaca.fetch_ohlcv("SPY", "1d", limit=1)
        assert len(bars) == 1
        assert isinstance(bars[0]["close"], Decimal)
        assert isinstance(bars[0]["open_time"], datetime)

    async def test_empty_barset_returns_empty_list(self, alpaca: AlpacaExchange) -> None:
        _d(alpaca).get_stock_bars.return_value = _fake_barset("SPY", [])

        bars = await alpaca.fetch_ohlcv("SPY", "1d", limit=10)
        assert bars == []

    async def test_missing_symbol_in_barset_returns_empty_list(
        self, alpaca: AlpacaExchange
    ) -> None:
        """BarSet.data may not contain the requested symbol if no data exists."""
        mock_response = MagicMock()
        mock_response.data = {}  # symbol absent — common when market is closed
        _d(alpaca).get_stock_bars.return_value = mock_response

        bars = await alpaca.fetch_ohlcv("SPY", "1d", limit=10)
        assert bars == []

    async def test_unsupported_timeframe_raises(self, alpaca: AlpacaExchange) -> None:
        with pytest.raises(ExchangeOrderError, match="Unsupported timeframe"):
            await alpaca.fetch_ohlcv("SPY", "3d")

    async def test_naive_timestamp_gets_utc(self, alpaca: AlpacaExchange) -> None:
        bar = self._make_bar()
        bar.timestamp = datetime(2024, 6, 1, 14, 30)  # noqa: DTZ001  # intentionally naive
        _d(alpaca).get_stock_bars.return_value = _fake_barset("SPY", [bar])

        bars = await alpaca.fetch_ohlcv("SPY", "1d", limit=1)
        assert bars[0]["open_time"].tzinfo is not None


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    async def test_active_account_returns_true(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_account.return_value = _fake_account()

        assert await alpaca.health_check() is True

    async def test_connection_error_returns_false(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_account.side_effect = ConnectionError("unreachable")

        assert await alpaca.health_check() is False


# ---------------------------------------------------------------------------
# Trade fees (commission-free)
# ---------------------------------------------------------------------------


class TestTradeFees:
    async def test_returns_zero_fees(self, alpaca: AlpacaExchange) -> None:
        fees = await alpaca.fetch_trade_fees("SPY")
        assert fees["maker"] == Decimal("0")
        assert fees["taker"] == Decimal("0")


# ---------------------------------------------------------------------------
# get_server_time
# ---------------------------------------------------------------------------


class TestGetServerTime:
    async def test_returns_utc_aware_datetime(self, alpaca: AlpacaExchange) -> None:
        _t(alpaca).get_clock.return_value = _fake_clock()

        t = await alpaca.get_server_time()
        assert t.tzinfo is not None


# ---------------------------------------------------------------------------
# Factory wiring
# ---------------------------------------------------------------------------


class TestFactory:
    def test_factory_passes_base_url_to_adapter(self) -> None:
        """get_exchange(ALPACA) must forward settings.alpaca.base_url as trading_base_url."""
        from unittest.mock import patch as _patch

        with (
            _patch("trading_bot.exchange.alpaca.TradingClient") as mock_tc,
            _patch("trading_bot.exchange.alpaca.StockHistoricalDataClient"),
            _patch(
                "trading_bot.exchange.factory.get_settings",
                return_value=_make_mock_settings(),
            ),
        ):
            from trading_bot.exchange.factory import get_exchange

            get_exchange(ExchangeId.ALPACA)

        call_kwargs: dict[str, Any] = dict(mock_tc.call_args.kwargs)
        assert call_kwargs.get("url_override") == "https://paper-api.alpaca.markets"


def _make_mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.alpaca.api_key = "k"
    settings.alpaca.secret_key = "s"
    settings.alpaca.paper = True
    settings.alpaca.base_url = "https://paper-api.alpaca.markets"
    settings.alpaca.allowed_etf_symbols = ["SPY", "QQQ", "SOXX", "IBIT"]
    settings.alpaca.allow_live_trading = False
    return settings
