"""Technical indicator functions — pure, stateless, pandas-based.

All inputs are pd.Series of closing prices, sorted oldest-first.
All outputs are pd.Series of the same length with NaN for the warm-up period.
No external TA libraries needed — pandas + numpy only.
"""

from __future__ import annotations

import pandas as pd


def sma(prices: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average over `period` bars."""
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    return prices.rolling(window=period, min_periods=period).mean()


def ema(prices: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average over `period` bars (standard alpha = 2/(n+1))."""
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    return prices.ewm(span=period, adjust=False, min_periods=period).mean()


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


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's smoothing).

    True Range = max(high-low, |high-prev_close|, |low-prev_close|).
    ATR = Wilder EMA of TR (alpha = 1/period). NaN for the warm-up period.
    Inputs must be aligned OHLC series sorted oldest-first.
    """
    if period < 1:
        raise ValueError(f"period must be >= 1, got {period}")
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
