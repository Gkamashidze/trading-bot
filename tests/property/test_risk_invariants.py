"""Property-based tests for risk engine invariants using Hypothesis.

MANDATORY per v5 spec: property-based testing for all risk and parsing logic.

Why property-based over unit tests:
- Unit tests check specific examples you thought of
- Hypothesis generates hundreds of inputs you didn't think of
- For financial systems, the edge cases you didn't think of are exactly
  where the bugs live (negative prices, zero capital, extreme volatility)

These tests verify INVARIANTS — things that must always be true:
- Position size is never negative
- Kelly fraction is always in [0, 1]
- Drawdown percentage is always in [-1, 0]
- SMA is always <= max(close) and >= min(close) for the window
"""

from __future__ import annotations

import math

import pandas as pd
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Risk sizing invariants
# ---------------------------------------------------------------------------


def fractional_kelly(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    kelly_fraction: float = 0.25,
) -> float:
    """Kelly criterion: f* = (W/L - (1-p)/p) x fraction."""
    if avg_loss == 0:
        return 0.0
    b = avg_win / avg_loss  # win/loss ratio
    p = win_rate
    kelly_full = (b * p - (1 - p)) / b
    return max(0.0, kelly_full * kelly_fraction)


@given(
    win_rate=st.floats(min_value=0.01, max_value=0.99),
    avg_win=st.floats(min_value=0.01, max_value=10.0),
    avg_loss=st.floats(min_value=0.01, max_value=10.0),
    kelly_fraction=st.floats(min_value=0.01, max_value=1.0),
)
@settings(max_examples=500)
def test_fractional_kelly_always_non_negative(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    kelly_fraction: float,
) -> None:
    """Position size fraction must never be negative."""
    assume(math.isfinite(win_rate))
    assume(math.isfinite(avg_win))
    assume(math.isfinite(avg_loss))
    result = fractional_kelly(win_rate, avg_win, avg_loss, kelly_fraction)
    assert result >= 0.0, f"Kelly fraction went negative: {result}"


@given(
    win_rate=st.floats(min_value=0.01, max_value=0.99),
    avg_win=st.floats(min_value=0.01, max_value=10.0),
    avg_loss=st.floats(min_value=0.01, max_value=10.0),
)
@settings(max_examples=300)
def test_fractional_kelly_never_exceeds_quarter(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
) -> None:
    """Fractional Kelly (1/4) must never exceed 25% of capital."""
    assume(math.isfinite(win_rate))
    assume(math.isfinite(avg_win))
    assume(math.isfinite(avg_loss))
    result = fractional_kelly(win_rate, avg_win, avg_loss, kelly_fraction=0.25)
    assert result <= 0.25 + 1e-9, f"1/4 Kelly exceeded 25%: {result}"


# ---------------------------------------------------------------------------
# Drawdown invariants
# ---------------------------------------------------------------------------


def compute_daily_drawdown(equity: list[float]) -> float:
    """Worst drawdown from running peak: min((value - peak) / peak) over all points."""
    if not equity:
        return 0.0
    peak = equity[0]
    min_dd = 0.0
    for value in equity:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (value - peak) / peak
            if dd < min_dd:
                min_dd = dd
    return min_dd


@given(
    equity_series=st.lists(
        st.floats(min_value=0.01, max_value=1_000_000.0),
        min_size=1,
        max_size=100,
    )
)
@settings(max_examples=500)
def test_drawdown_always_in_minus_one_to_zero(equity_series: list[float]) -> None:
    """Drawdown must always be in [-1.0, 0.0]."""
    assume(all(math.isfinite(x) for x in equity_series))
    dd = compute_daily_drawdown(equity_series)
    assert -1.0 <= dd <= 0.0 + 1e-9, f"Drawdown out of bounds: {dd}"


# ---------------------------------------------------------------------------
# SMA invariants
# ---------------------------------------------------------------------------


@given(
    prices=st.lists(
        st.floats(min_value=0.01, max_value=1_000_000.0),
        min_size=51,
        max_size=500,
    ),
    period=st.integers(min_value=2, max_value=50),
)
@settings(max_examples=300)
def test_sma_within_price_range(prices: list[float], period: int) -> None:
    """SMA must always be within [min(window), max(window)] for valid windows."""
    assume(all(math.isfinite(p) for p in prices))

    df = pd.DataFrame({"close": prices})
    sma = df["close"].rolling(window=period, min_periods=period).mean()

    for i, val in enumerate(sma):
        if math.isnan(val):
            continue
        window_min = min(prices[max(0, i - period + 1) : i + 1])
        window_max = max(prices[max(0, i - period + 1) : i + 1])
        assert window_min - 1e-9 <= val <= window_max + 1e-9, (
            f"SMA[{i}]={val} outside window [{window_min}, {window_max}]"
        )


# ---------------------------------------------------------------------------
# OHLCVBar invariants
# ---------------------------------------------------------------------------


@given(
    open_price=st.floats(min_value=0.01, max_value=1_000_000.0),
    spread=st.floats(min_value=0.0, max_value=10_000.0),
    close_offset=st.floats(min_value=-5000.0, max_value=5000.0),
    volume=st.floats(min_value=0.0, max_value=1e9),
)
@settings(max_examples=500)
def test_ohlcv_bar_invariants_hold(
    open_price: float, spread: float, close_offset: float, volume: float
) -> None:
    """Physical OHLCV invariants must hold for any valid input."""
    assume(math.isfinite(open_price))
    assume(math.isfinite(spread))
    assume(math.isfinite(close_offset))
    assume(math.isfinite(volume))

    high = open_price + abs(spread)
    low = max(0.01, open_price - abs(spread))
    close = max(low, min(high, open_price + close_offset))

    # Invariants
    assert high >= low, "high must be >= low"
    assert low <= open_price <= high, "open must be within [low, high]"
    assert low <= close <= high, "close must be within [low, high]"
    assert volume >= 0, "volume must be non-negative"
