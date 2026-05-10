"""Property-based tests for backtesting engine invariants (Hypothesis)."""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.metrics import compute_metrics
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy


def _make_bars(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    dates = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open_time": dates,
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [max(c - 1, 0.01) for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


# ---------------------------------------------------------------------------
# Equity invariants
# ---------------------------------------------------------------------------


@given(
    closes=st.lists(
        st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False),
        min_size=20,
        max_size=100,
    ),
    fee_rate=st.floats(min_value=0.0, max_value=0.05),
    slippage=st.floats(min_value=0.0, max_value=0.02),
)
@settings(max_examples=200)
def test_equity_never_negative(closes: list[float], fee_rate: float, slippage: float) -> None:
    """Equity must be >= 0 for any price path and any valid fee/slippage."""
    bars = _make_bars(closes)
    strat = SmaCrossoverStrategy(fast=3, slow=5)
    assume(len(bars) >= strat.min_bars_required)

    cfg = BacktestConfig(fee_rate=fee_rate, slippage_rate=slippage)
    engine = BacktestEngine(cfg)
    result = engine.run(bars, strat)
    assert (result.equity_curve >= 0).all()


@given(
    closes=st.lists(
        st.floats(min_value=1.0, max_value=100_000.0, allow_nan=False, allow_infinity=False),
        min_size=20,
        max_size=100,
    )
)
@settings(max_examples=200)
def test_equity_length_equals_bars(closes: list[float]) -> None:
    """Equity curve length must equal input bar count."""
    bars = _make_bars(closes)
    strat = SmaCrossoverStrategy(fast=3, slow=5)
    assume(len(bars) >= strat.min_bars_required)

    engine = BacktestEngine()
    result = engine.run(bars, strat)
    assert len(result.equity_curve) == len(bars)


# ---------------------------------------------------------------------------
# Metrics invariants
# ---------------------------------------------------------------------------


@given(
    wins=st.lists(st.floats(min_value=0.001, max_value=1.0), min_size=0, max_size=20),
    losses=st.lists(st.floats(min_value=-1.0, max_value=-0.001), min_size=0, max_size=20),
)
@settings(max_examples=300)
def test_win_rate_in_valid_range(wins: list[float], losses: list[float]) -> None:
    """Win rate must always be in [0, 100]."""
    idx = pd.date_range("2023-01-01", periods=10, freq="D", tz="UTC")
    eq = pd.Series(10_000.0, index=idx)
    in_pos = pd.Series(False, index=idx)
    m = compute_metrics(eq, wins + losses, in_pos)
    assert 0.0 <= m.win_rate <= 100.0


@given(
    trades=st.lists(
        st.floats(min_value=-0.5, max_value=0.5, allow_nan=False, allow_infinity=False),
        min_size=0,
        max_size=50,
    )
)
@settings(max_examples=300)
def test_profit_factor_non_negative(trades: list[float]) -> None:
    """Profit factor is always >= 0."""
    idx = pd.date_range("2023-01-01", periods=10, freq="D", tz="UTC")
    eq = pd.Series(10_000.0, index=idx)
    in_pos = pd.Series(False, index=idx)
    m = compute_metrics(eq, trades, in_pos)
    assert m.profit_factor >= 0.0


@given(
    n=st.integers(min_value=2, max_value=500),
)
@settings(max_examples=100)
def test_max_drawdown_non_positive(n: int) -> None:
    """Max drawdown is always <= 0 (it's a loss, never a gain)."""
    idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    vals = [10_000.0 * (1.0 + i * 0.001) for i in range(n)]
    eq = pd.Series(vals, index=idx)
    in_pos = pd.Series(False, index=idx)
    m = compute_metrics(eq, [], in_pos)
    assert m.max_drawdown_pct <= 0.0


@given(
    n=st.integers(min_value=10, max_value=500),
    daily_growth=st.floats(min_value=0.0001, max_value=0.005),
)
@settings(max_examples=100)
def test_positive_equity_implies_positive_total_return(n: int, daily_growth: float) -> None:
    """Strictly increasing equity → total return > 0."""
    idx = pd.date_range("2023-01-01", periods=n, freq="D", tz="UTC")
    vals = [10_000.0 * (1.0 + daily_growth) ** i for i in range(n)]
    eq = pd.Series(vals, index=idx)
    in_pos = pd.Series(True, index=idx)
    m = compute_metrics(eq, [0.01], in_pos)
    assert m.total_return_pct > 0.0


@given(
    capital=st.floats(min_value=100.0, max_value=1_000_000.0),
)
@settings(max_examples=100)
def test_initial_capital_preserved_no_trades(capital: float) -> None:
    """With no signals fired, final equity equals initial capital."""
    strat = SmaCrossoverStrategy(fast=3, slow=5)
    closes = [100.0] * 20
    bars = _make_bars(closes)
    engine = BacktestEngine(BacktestConfig(initial_capital=capital))
    result = engine.run(bars, strat)
    assert result.equity_curve.iloc[-1] == pytest.approx(capital, rel=0.001)
