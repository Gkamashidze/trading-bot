"""Unit tests for the walk-forward / OOS backtest harness.

Uses synthetic price data. Verifies windowing, the buy-and-hold benchmark, the
precomputed-signal wrapper, and the no-look-ahead invariant (each test window
starts strictly after its train window ends).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.walk_forward import (
    PrecomputedSignalStrategy,
    _buy_and_hold,
    run_walk_forward,
)
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy


def _synth_bars(n: int = 400, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0004, 0.01, n).cumsum()
    close = 100.0 * np.exp(steps)
    open_ = np.concatenate([[100.0], close[:-1]])
    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "open_time": [t0 + timedelta(hours=i) for i in range(n)],
            "open": open_,
            "high": np.maximum(open_, close) * 1.001,
            "low": np.minimum(open_, close) * 0.999,
            "close": close,
            "volume": rng.uniform(10, 100, n),
        }
    )


_GRID = [{"fast": 5, "slow": 10}, {"fast": 10, "slow": 20}]


def _factory(p: dict) -> SmaCrossoverStrategy:
    return SmaCrossoverStrategy(**p)


class TestBuyAndHold:
    def test_return_matches_price_change_minus_fee(self) -> None:
        bars = _synth_bars(50)
        cfg = BacktestConfig(fee_rate=0.001, annual_trading_days=24 * 365)
        metrics, equity = _buy_and_hold(bars, cfg)
        # Equity is rebased to the first bar's close, so the fee cancels in the
        # return ratio: return = close[-1]/close[0] - 1.
        first_close = float(bars["close"].iloc[0])
        final_price = float(bars["close"].iloc[-1])
        expected = (final_price / first_close - 1.0) * 100.0
        assert abs(metrics.total_return_pct - expected) < 0.01
        assert len(equity) == len(bars)


class TestPrecomputedSignalStrategy:
    def test_returns_stored_signals(self) -> None:
        signals = pd.Series(["HOLD", "BUY", "SELL", "HOLD"])
        strat = PrecomputedSignalStrategy(signals)
        bars = _synth_bars(4)
        out = strat.backtest_signals(bars)
        assert list(out) == ["HOLD", "BUY", "SELL", "HOLD"]


class TestWalkForward:
    def test_window_count(self) -> None:
        bars = _synth_bars(400)
        result = run_walk_forward(
            bars,
            strategy_id="sma_crossover",
            symbol="BTC/USDT",
            factory=_factory,
            param_grid=_GRID,
            train_bars=100,
            test_bars=50,
        )
        # floor((400 - 100) / 50) = 6 windows
        assert len(result.windows) == 6

    def test_no_lookahead_test_starts_after_train_ends(self) -> None:
        bars = _synth_bars(400)
        result = run_walk_forward(
            bars,
            strategy_id="sma_crossover",
            symbol="BTC/USDT",
            factory=_factory,
            param_grid=_GRID,
            train_bars=100,
            test_bars=50,
        )
        for w in result.windows:
            assert w.train_end < w.test_start  # params come strictly from the past

    def test_produces_oos_and_benchmark(self) -> None:
        bars = _synth_bars(400)
        result = run_walk_forward(
            bars,
            strategy_id="sma_crossover",
            symbol="BTC/USDT",
            factory=_factory,
            param_grid=_GRID,
            train_bars=100,
            test_bars=50,
        )
        assert not result.oos_equity_curve.empty
        assert not result.benchmark_equity_curve.empty
        assert result.benchmark_metrics.total_trades == 1
        assert isinstance(result.beats_benchmark, bool)

    def test_raises_on_insufficient_bars(self) -> None:
        bars = _synth_bars(120)
        with pytest.raises(ValueError, match="need >"):
            run_walk_forward(
                bars,
                strategy_id="sma_crossover",
                symbol="BTC/USDT",
                factory=_factory,
                param_grid=_GRID,
                train_bars=100,
                test_bars=50,
            )
