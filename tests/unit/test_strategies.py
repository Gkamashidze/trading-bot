"""Unit tests for strategy indicators and signal generation."""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from trading_bot.strategies.indicators import rsi, sma
from trading_bot.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(closes: list[float]) -> pd.DataFrame:
    """Build a minimal bars DataFrame from a list of closing prices."""
    n = len(closes)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    dates = pd.date_range(start=start, periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": dates,
            "open": closes,
            "high": [c + 100 for c in closes],
            "low": [c - 100 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


# ---------------------------------------------------------------------------
# SMA indicator
# ---------------------------------------------------------------------------


class TestSma:
    def test_sma_basic(self) -> None:
        prices = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(prices, 3)
        assert math.isnan(result.iloc[0])
        assert math.isnan(result.iloc[1])
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[4] == pytest.approx(4.0)

    def test_sma_period_1_equals_input(self) -> None:
        prices = pd.Series([10.0, 20.0, 30.0])
        result = sma(prices, 1)
        assert list(result) == pytest.approx([10.0, 20.0, 30.0])

    def test_sma_invalid_period(self) -> None:
        with pytest.raises(ValueError, match="period must be >= 1"):
            sma(pd.Series([1.0, 2.0]), 0)


# ---------------------------------------------------------------------------
# RSI indicator
# ---------------------------------------------------------------------------


class TestRsi:
    def test_rsi_flat_prices_is_nan_or_50(self) -> None:
        prices = pd.Series([100.0] * 20)
        result = rsi(prices, 14)
        # With constant prices, all gains=0, all losses=0 → NaN or ~50
        # First 14 values are NaN due to min_periods
        assert result.iloc[:14].isna().all()

    def test_rsi_always_rising_approaches_100(self) -> None:
        # Monotonically rising prices → RSI should be high (>70)
        prices = pd.Series([float(i) for i in range(1, 51)])
        result = rsi(prices, 14)
        valid = result.dropna()
        assert (valid > 70).all()

    def test_rsi_always_falling_approaches_0(self) -> None:
        prices = pd.Series([float(i) for i in range(50, 0, -1)])
        result = rsi(prices, 14)
        valid = result.dropna()
        assert (valid < 30).all()

    def test_rsi_range_0_to_100(self) -> None:
        rng = np.random.default_rng(42)
        prices = pd.Series(rng.normal(100, 10, 100))
        result = rsi(prices, 14).dropna()
        assert (result >= 0).all()
        assert (result <= 100).all()

    def test_rsi_invalid_period(self) -> None:
        with pytest.raises(ValueError, match="period must be >= 2"):
            rsi(pd.Series([1.0, 2.0]), 1)


# ---------------------------------------------------------------------------
# SmaCrossoverStrategy
# ---------------------------------------------------------------------------


class TestSmaCrossoverStrategy:
    def test_insufficient_bars_returns_hold(self) -> None:
        strat = SmaCrossoverStrategy(fast=20, slow=50)
        bars = _make_bars([50000.0] * 30)  # need 52 bars
        result = strat.compute(bars)
        assert result.signal == "HOLD"
        assert result.strength == 0.0
        assert "insufficient" in result.reason

    def test_bullish_trend_hold(self) -> None:
        strat = SmaCrossoverStrategy(fast=5, slow=10)
        # Rising prices → fast SMA > slow SMA but no fresh crossover
        prices = list(range(100, 115))  # 15 bars > slow+2=12
        bars = _make_bars(prices)
        result = strat.compute(bars)
        assert result.signal == "HOLD"
        assert result.strength >= 0.0

    def test_bearish_trend_hold(self) -> None:
        strat = SmaCrossoverStrategy(fast=5, slow=10)
        prices = list(range(115, 100, -1))  # declining
        bars = _make_bars(prices)
        result = strat.compute(bars)
        assert result.signal == "HOLD"

    def test_golden_cross_produces_buy(self) -> None:
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        # 10 bars flat at 10, then 1 bar spike to 100:
        # prev: SMA3=SMA5=10 (equal → fast_prev <= slow_prev)
        # last: SMA3=mean(10,10,100)=40, SMA5=mean(10,10,10,10,100)=28 → fast > slow
        prices = [10.0] * 10 + [100.0]
        bars = _make_bars(prices)
        result = strat.compute(bars)
        assert result.signal == "BUY"
        assert result.strength > 0

    def test_invalid_fast_slow(self) -> None:
        with pytest.raises(ValueError):
            SmaCrossoverStrategy(fast=50, slow=20)

    def test_indicators_present(self) -> None:
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        prices = [float(i) for i in range(1, 15)]
        bars = _make_bars(prices)
        result = strat.compute(bars)
        assert "sma_3" in result.indicators
        assert "sma_5" in result.indicators
        assert "gap_pct" in result.indicators


# ---------------------------------------------------------------------------
# RsiMeanReversionStrategy
# ---------------------------------------------------------------------------


class TestRsiMeanReversionStrategy:
    def test_insufficient_bars_returns_hold(self) -> None:
        strat = RsiMeanReversionStrategy(period=14)
        bars = _make_bars([50000.0] * 10)
        result = strat.compute(bars)
        assert result.signal == "HOLD"
        assert "insufficient" in result.reason

    def test_oversold_produces_buy(self) -> None:
        strat = RsiMeanReversionStrategy(period=14, oversold=30.0, overbought=70.0)
        # Steadily falling prices → RSI < 30
        prices = [float(i) for i in range(200, 170, -1)]
        bars = _make_bars(prices)
        result = strat.compute(bars)
        assert result.signal == "BUY"
        assert result.strength > 0

    def test_overbought_produces_sell(self) -> None:
        strat = RsiMeanReversionStrategy(period=14, oversold=30.0, overbought=70.0)
        # Steadily rising prices → RSI > 70
        prices = [float(i) for i in range(100, 135)]
        bars = _make_bars(prices)
        result = strat.compute(bars)
        assert result.signal == "SELL"
        assert result.strength > 0

    def test_neutral_zone_is_hold(self) -> None:
        strat = RsiMeanReversionStrategy(period=14, oversold=30.0, overbought=70.0)
        # Oscillating prices → RSI near 50
        rng = np.random.default_rng(0)
        prices = list(100.0 + rng.normal(0, 1, 50))
        bars = _make_bars(prices)
        result = strat.compute(bars)
        assert result.signal == "HOLD"

    def test_rsi_in_indicators(self) -> None:
        strat = RsiMeanReversionStrategy(period=5)
        prices = [float(i) for i in range(1, 20)]
        bars = _make_bars(prices)
        result = strat.compute(bars)
        assert "rsi" in result.indicators
        assert 0.0 <= result.indicators["rsi"] <= 100.0

    def test_invalid_thresholds(self) -> None:
        with pytest.raises(ValueError):
            RsiMeanReversionStrategy(oversold=70.0, overbought=30.0)
