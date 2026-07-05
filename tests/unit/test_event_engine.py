"""Unit tests for the event-driven bracket backtester + Trend Pullback signals.

The cash-accounting invariant (equity == cash when flat; no mark-to-market
double counting) is the critical regression guard — an earlier version inflated
in-position equity by the cost basis, corrupting drawdown and Sharpe.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trading_bot.backtesting.event_engine import (
    EXIT_STOP,
    EXIT_TAKE_PROFIT,
    BracketConfig,
    buy_and_hold_equity,
    run_bracket_backtest,
)
from trading_bot.strategies.indicators import atr, ema
from trading_bot.strategies.trend_pullback import (
    TrendPullbackParams,
    compute_trend_pullback_signals,
)


def _bars(prices: list[float], highs: list[float] | None = None, lows: list[float] | None = None):
    n = len(prices)
    times = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": times,
            "open": prices,
            "high": highs if highs is not None else prices,
            "low": lows if lows is not None else prices,
            "close": prices,
            "volume": [100.0] * n,
        }
    )


class TestIndicators:
    def test_ema_matches_pandas(self) -> None:
        prices = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = ema(prices, 3).dropna()
        assert len(result) == 3
        assert result.iloc[-1] > result.iloc[0]

    def test_ema_invalid_period(self) -> None:
        with pytest.raises(ValueError):
            ema(pd.Series([1.0]), 0)

    def test_atr_is_positive_and_warms_up(self) -> None:
        high = pd.Series([10.0, 11.0, 12.0, 11.5, 13.0, 12.0])
        low = pd.Series([9.0, 10.0, 11.0, 10.5, 12.0, 11.0])
        close = pd.Series([9.5, 10.5, 11.5, 11.0, 12.5, 11.5])
        result = atr(high, low, close, period=3)
        assert result.iloc[:2].isna().all()  # warm-up NaN
        assert (result.dropna() > 0).all()

    def test_atr_constant_range(self) -> None:
        # Every bar spans exactly 2.0 with no gaps → ATR converges to 2.0.
        high = pd.Series([12.0] * 20)
        low = pd.Series([10.0] * 20)
        close = pd.Series([11.0] * 20)
        result = atr(high, low, close, period=5)
        assert result.iloc[-1] == pytest.approx(2.0, abs=1e-6)


class TestCashAccounting:
    def test_equity_flat_when_no_entries(self) -> None:
        bars = _bars([100.0] * 10)
        entries = pd.Series([False] * 10)
        atr_s = pd.Series([1.0] * 10)
        trend = pd.Series([True] * 10)
        res = run_bracket_backtest(
            bars, entries, atr_s, trend, BracketConfig(initial_capital=5000.0)
        )
        assert (res.equity_curve == 5000.0).all()
        assert res.trades == []

    def test_no_mark_to_market_double_count(self) -> None:
        # Enter, hold flat price, exit at end. Equity must never exceed capital
        # by more than rounding — the old bug spiked it ~2x while in position.
        bars = _bars([100.0] * 20)
        entries = pd.Series([i == 0 for i in range(20)])  # signal on bar 0 → enter bar 1
        atr_s = pd.Series([1.0] * 20)
        trend = pd.Series([True] * 20)
        cfg = BracketConfig(initial_capital=10_000.0, max_hold_bars=100)
        res = run_bracket_backtest(bars, entries, atr_s, trend, cfg)
        # Flat price + fees/slippage → equity slightly below capital, never ~2x.
        assert res.equity_curve.max() <= 10_050.0
        assert res.equity_curve.min() >= 9_000.0

    def test_winning_trade_increases_equity(self) -> None:
        # Price ramps up so the take-profit at +3 ATR triggers.
        prices = [100.0 + i for i in range(30)]
        highs = [p + 0.5 for p in prices]
        lows = [p - 0.5 for p in prices]
        bars = _bars(prices, highs, lows)
        entries = pd.Series([i == 0 for i in range(30)])
        atr_s = pd.Series([1.0] * 30)
        trend = pd.Series([True] * 30)
        res = run_bracket_backtest(bars, entries, atr_s, trend, BracketConfig(tp_atr_mult=3.0))
        assert len(res.trades) == 1
        assert res.trades[0].exit_reason == EXIT_TAKE_PROFIT
        assert res.equity_curve.iloc[-1] > 10_000.0


class TestBracketExits:
    def test_stop_loss_triggers_on_low(self) -> None:
        # Enter at bar 1 (~100), then bar 2 dips below the stop (100 - 1.5*ATR).
        prices = [100.0, 100.0, 100.0, 100.0]
        highs = [101.0, 101.0, 101.0, 101.0]
        lows = [99.0, 99.0, 90.0, 99.0]  # bar 2 low = 90 → stop hit
        bars = _bars(prices, highs, lows)
        entries = pd.Series([True, False, False, False])
        atr_s = pd.Series([2.0] * 4)
        trend = pd.Series([True] * 4)
        res = run_bracket_backtest(bars, entries, atr_s, trend, BracketConfig(sl_atr_mult=1.5))
        assert len(res.trades) == 1
        assert res.trades[0].exit_reason == EXIT_STOP

    def test_regime_break_exits_position(self) -> None:
        prices = [100.0] * 6
        bars = _bars(prices)
        entries = pd.Series([True, False, False, False, False, False])
        atr_s = pd.Series([1.0] * 6)
        trend = pd.Series([True, True, True, False, False, False])  # regime off at bar 3
        res = run_bracket_backtest(bars, entries, atr_s, trend, BracketConfig())
        assert len(res.trades) == 1
        assert res.trades[0].exit_reason == "regime_change"

    def test_no_entry_when_regime_off(self) -> None:
        bars = _bars([100.0] * 5)
        entries = pd.Series([True, True, True, True, True])
        atr_s = pd.Series([1.0] * 5)
        trend = pd.Series([False] * 5)  # never active
        res = run_bracket_backtest(bars, entries, atr_s, trend, BracketConfig())
        assert res.trades == []


class TestBuyAndHold:
    def test_buy_and_hold_tracks_price(self) -> None:
        bars = _bars([100.0, 110.0, 120.0])
        eq = buy_and_hold_equity(bars, initial_capital=1000.0)
        # units = 1000/100 = 10; final = 10 * 120 = 1200
        assert eq.iloc[-1] == pytest.approx(1200.0)


class TestTrendPullbackSignals:
    def test_returns_aligned_series(self) -> None:
        n = 300
        prices = [100.0 + np.sin(i / 10) * 5 for i in range(n)]
        bars = _bars(prices, [p + 1 for p in prices], [p - 1 for p in prices])
        sig = compute_trend_pullback_signals(bars, TrendPullbackParams())
        assert len(sig.entries) == n
        assert len(sig.atr_series) == n
        assert len(sig.trend_active) == n
        assert sig.entries.dtype == bool

    def test_no_lookahead_early_bars_have_no_trend(self) -> None:
        # Before the daily SMA200 warms up (~200 days), trend must be inactive.
        n = 500
        prices = [100.0 + i * 0.1 for i in range(n)]
        bars = _bars(prices, [p + 1 for p in prices], [p - 1 for p in prices])
        sig = compute_trend_pullback_signals(bars, TrendPullbackParams())
        # First day's bars can't know a 200-day SMA → no trend, no entries.
        assert not sig.trend_active.iloc[:24].any()
        assert not sig.entries.iloc[:24].any()
