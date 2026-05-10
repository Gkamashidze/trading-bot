"""Technical indicator functions — pure, stateless, pandas-based.

All inputs are pd.Series of closing prices, sorted oldest-first.
All outputs are pd.Series of the same length with NaN for the warm-up period.
No external TA libraries needed — pandas + numpy only.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(prices: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average over `period` bars."""
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    return prices.rolling(window=period, min_periods=period).mean()


def rsi(prices: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's RSI (Relative Strength Index).

    Uses exponential smoothing with alpha = 1/period (Wilder's method).
    Output range: 0-100. NaN for the first `period` values.
    """
    if period < 2:
        raise ValueError(f"period must be >= 2, got {period}")
    delta = prices.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    # pandas: 0/0 = NaN (no movement), x/0 = inf → RSI = 100 (all gains)
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))
