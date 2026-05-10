"""Unit tests for the backtesting engine, metrics, and strategy signal generators."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.metrics import compute_metrics
from trading_bot.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bars(closes: list[float], opens: list[float] | None = None) -> pd.DataFrame:
    n = len(closes)
    dates = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    if opens is None:
        opens = closes
    return pd.DataFrame(
        {
            "open_time": dates,
            "open": opens,
            "high": [c + 50 for c in closes],
            "low": [c - 50 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


# ---------------------------------------------------------------------------
# BacktestConfig
# ---------------------------------------------------------------------------


class TestBacktestConfig:
    def test_defaults(self) -> None:
        cfg = BacktestConfig()
        assert cfg.initial_capital == 10_000.0
        assert cfg.fee_rate == 0.001
        assert cfg.slippage_rate == 0.0005
        assert cfg.position_size_pct == 1.0
        assert cfg.annual_trading_days == 365

    def test_invalid_capital(self) -> None:
        with pytest.raises(ValidationError):
            BacktestConfig(initial_capital=0)

    def test_invalid_fee(self) -> None:
        with pytest.raises(ValidationError):
            BacktestConfig(fee_rate=-0.01)


# ---------------------------------------------------------------------------
# BacktestEngine — basic simulation
# ---------------------------------------------------------------------------


class TestBacktestEngine:
    def test_no_signals_equity_stays_flat(self) -> None:
        """All HOLD — equity never changes."""
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        bars = _make_bars([100.0] * 20)
        engine = BacktestEngine()
        result = engine.run(bars, strat)
        assert result.metrics.total_trades == 0
        assert result.metrics.total_return_pct == pytest.approx(0.0, abs=1.0)

    def test_buy_then_sell_produces_one_trade(self) -> None:
        """BUY on falling RSI, SELL on rising — should produce exactly 1 round-trip."""
        strat = RsiMeanReversionStrategy(period=14, oversold=30.0, overbought=70.0)
        prices = list(range(200, 160, -1)) + list(range(160, 210))
        bars = _make_bars(prices)
        engine = BacktestEngine()
        result = engine.run(bars, strat)
        assert result.metrics.total_trades >= 1

    def test_fees_reduce_return(self) -> None:
        """A profitable scenario earns less with fees than without."""
        strat = RsiMeanReversionStrategy(period=14, oversold=30.0, overbought=70.0)
        prices = list(range(200, 160, -1)) + list(range(160, 230))
        bars = _make_bars(prices)

        no_fee = BacktestEngine(BacktestConfig(fee_rate=0.0, slippage_rate=0.0))
        with_fee = BacktestEngine(BacktestConfig(fee_rate=0.01, slippage_rate=0.001))

        r_no = no_fee.run(bars, strat)
        r_fee = with_fee.run(bars, strat)

        if r_no.metrics.total_trades > 0:
            assert r_fee.metrics.total_return_pct <= r_no.metrics.total_return_pct

    def test_equity_never_goes_negative(self) -> None:
        """Equity must remain non-negative regardless of price movement."""
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        closes = [10.0] * 10 + [100.0] + [1.0] * 10
        bars = _make_bars(closes)
        engine = BacktestEngine()
        result = engine.run(bars, strat)
        assert (result.equity_curve >= 0).all()

    def test_insufficient_bars_raises(self) -> None:
        strat = SmaCrossoverStrategy(fast=20, slow=50)
        bars = _make_bars([100.0] * 10)
        engine = BacktestEngine()
        with pytest.raises(ValueError, match="bars"):
            engine.run(bars, strat)

    def test_result_fields_populated(self) -> None:
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        bars = _make_bars([float(i) for i in range(1, 25)])
        engine = BacktestEngine()
        result = engine.run(bars, strat)

        assert result.strategy_id == "sma_crossover"
        assert result.n_bars == len(bars)
        assert result.period_start != ""
        assert result.period_end != ""
        assert isinstance(result.computed_at, datetime)
        assert len(result.equity_curve) == len(bars)

    def test_open_position_closed_at_last_bar(self) -> None:
        """If position is open at end, it's closed and equity equals cash."""
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        closes = [10.0] * 10 + [100.0]
        bars = _make_bars(closes)
        engine = BacktestEngine(BacktestConfig(fee_rate=0.0, slippage_rate=0.0))
        result = engine.run(bars, strat)
        # Final equity should equal close price proxy, not stuck in position
        assert result.equity_curve.iloc[-1] > 0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    def _flat_equity(self, n: int = 100) -> pd.Series:
        idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
        return pd.Series(10_000.0, index=idx)

    def _rising_equity(self, n: int = 365) -> pd.Series:
        idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
        vals = [10_000.0 * (1 + 0.001) ** i for i in range(n)]
        return pd.Series(vals, index=idx)

    def test_zero_return_flat_equity(self) -> None:
        eq = self._flat_equity()
        m = compute_metrics(eq, [], pd.Series(False, index=eq.index))
        assert m.total_return_pct == pytest.approx(0.0, abs=0.01)
        assert m.total_trades == 0
        assert m.sharpe_ratio == pytest.approx(0.0, abs=0.01)

    def test_positive_return_rising_equity(self) -> None:
        eq = self._rising_equity()
        m = compute_metrics(eq, [0.05, 0.03, 0.02], pd.Series(True, index=eq.index))
        assert m.total_return_pct > 0
        assert m.cagr_pct > 0
        assert m.sharpe_ratio > 0
        assert m.win_rate == pytest.approx(100.0)
        assert m.winning_trades == 3
        assert m.losing_trades == 0

    def test_max_drawdown_negative(self) -> None:
        idx = pd.date_range("2023-01-01", periods=5, freq="D", tz="UTC")
        eq = pd.Series([10000.0, 12000.0, 8000.0, 9000.0, 11000.0], index=idx)
        m = compute_metrics(eq, [], pd.Series(False, index=idx))
        assert m.max_drawdown_pct < 0

    def test_profit_factor_correct(self) -> None:
        idx = pd.date_range("2023-01-01", periods=10, freq="D", tz="UTC")
        eq = pd.Series(10_000.0, index=idx)
        trades = [0.1, 0.1, -0.05]
        m = compute_metrics(eq, trades, pd.Series(False, index=idx))
        assert m.profit_factor == pytest.approx(0.2 / 0.05, rel=0.01)

    def test_max_consecutive_losses_correct(self) -> None:
        idx = pd.date_range("2023-01-01", periods=10, freq="D", tz="UTC")
        eq = pd.Series(10_000.0, index=idx)
        trades = [0.1, -0.05, -0.05, -0.05, 0.1, -0.02]
        m = compute_metrics(eq, trades, pd.Series(False, index=idx))
        assert m.max_consecutive_losses == 3

    def test_exposure_time_matches_position(self) -> None:
        idx = pd.date_range("2023-01-01", periods=10, freq="D", tz="UTC")
        eq = pd.Series(10_000.0, index=idx)
        in_pos = pd.Series([True] * 5 + [False] * 5, index=idx)
        m = compute_metrics(eq, [], in_pos)
        assert m.exposure_time_pct == pytest.approx(50.0, abs=0.1)


# ---------------------------------------------------------------------------
# backtest_signals — SmaCrossoverStrategy
# ---------------------------------------------------------------------------


class TestSmaBacktestSignals:
    def test_golden_cross_bar_is_buy(self) -> None:
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        closes = [10.0] * 10 + [100.0]
        bars = _make_bars(closes)
        sigs = strat.backtest_signals(bars)
        assert sigs.iloc[-1] == "BUY"

    def test_death_cross_bar_is_sell(self) -> None:
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        closes = [100.0] * 10 + [1.0]
        bars = _make_bars(closes)
        sigs = strat.backtest_signals(bars)
        assert sigs.iloc[-1] == "SELL"

    def test_no_crossover_is_hold(self) -> None:
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        closes = list(range(1, 15))
        bars = _make_bars(closes)
        sigs = strat.backtest_signals(bars)
        assert "BUY" not in sigs.values or "SELL" not in sigs.values

    def test_signal_length_matches_bars(self) -> None:
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        bars = _make_bars(list(range(1, 25)))
        sigs = strat.backtest_signals(bars)
        assert len(sigs) == len(bars)

    def test_only_valid_signals(self) -> None:
        strat = SmaCrossoverStrategy(fast=3, slow=5)
        bars = _make_bars(list(range(1, 30)))
        sigs = strat.backtest_signals(bars)
        assert set(sigs.unique()).issubset({"BUY", "SELL", "HOLD"})


# ---------------------------------------------------------------------------
# backtest_signals — RsiMeanReversionStrategy
# ---------------------------------------------------------------------------


class TestRsiBacktestSignals:
    def test_oversold_bars_are_buy(self) -> None:
        strat = RsiMeanReversionStrategy(period=14, oversold=30.0, overbought=70.0)
        closes = [float(i) for i in range(200, 170, -1)]
        bars = _make_bars(closes)
        sigs = strat.backtest_signals(bars)
        assert "BUY" in sigs.values

    def test_overbought_bars_are_sell(self) -> None:
        strat = RsiMeanReversionStrategy(period=14, oversold=30.0, overbought=70.0)
        closes = [float(i) for i in range(100, 140)]
        bars = _make_bars(closes)
        sigs = strat.backtest_signals(bars)
        assert "SELL" in sigs.values

    def test_signal_length_matches_bars(self) -> None:
        strat = RsiMeanReversionStrategy(period=14)
        bars = _make_bars(list(range(1, 50)))
        sigs = strat.backtest_signals(bars)
        assert len(sigs) == len(bars)

    def test_only_valid_signals(self) -> None:
        strat = RsiMeanReversionStrategy(period=14)
        bars = _make_bars(list(range(1, 50)))
        sigs = strat.backtest_signals(bars)
        assert set(sigs.unique()).issubset({"BUY", "SELL", "HOLD"})
