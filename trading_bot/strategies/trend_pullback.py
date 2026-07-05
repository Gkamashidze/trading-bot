"""Trend Pullback signal generator (STRATEGY_ROADMAP.md §3.2, BTC/USDT variant).

Hypothesis: in an established uptrend, buying oversold pullbacks (RSI dips then
recovers) beats buying breakouts, and an ATR bracket with a 2:1 reward:risk
turns a modest hit-rate into positive expectancy.

This module produces the three per-bar series the event-driven bracket engine
consumes: entry signals, ATR, and the regime (trend-active) filter. It does NOT
place brackets itself — ``event_engine.run_bracket_backtest`` owns exits.

Look-ahead safety (STRATEGY_ROADMAP.md §4.3): the daily trend filter is computed
on calendar-day resampled closes, then **shifted one day** so any 1h bar on day T
only ever sees the daily bar confirmed at the close of day T-1.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from trading_bot.strategies.indicators import atr, rsi, sma


@dataclass(frozen=True)
class TrendPullbackParams:
    """Tunable parameters (walk-forward optimisable)."""

    rsi_period: int = 14
    oversold_level: float = 35.0  # pullback confirmed below this
    recovery_level: float = 40.0  # recovery confirmed on cross back above
    recovery_window: int = 5  # oversold must have occurred within N prior bars
    atr_period: int = 14
    daily_sma_fast: int = 50  # daily SMA50 (golden-cross fast + entry structure)
    daily_sma_slow: int = 200  # daily SMA200 (macro trend)
    vol_window: int = 20
    vol_ratio_min: float = 0.5  # skip entries on abnormally low volume


@dataclass(frozen=True)
class TrendPullbackSignals:
    entries: pd.Series  # bool — True = enter at next bar open
    atr_series: pd.Series
    trend_active: pd.Series  # bool — regime filter (also gates + exits)


def compute_trend_pullback_signals(
    bars: pd.DataFrame, params: TrendPullbackParams | None = None
) -> TrendPullbackSignals:
    """Compute (entries, atr, trend_active) for the bracket engine.

    ``bars`` must have open/high/low/close/volume + a UTC ``open_time`` column,
    sorted oldest-first. Returned series are index-aligned to ``bars``.
    """
    p = params or TrendPullbackParams()
    idx = bars.index
    close = bars["close"].reset_index(drop=True)
    high = bars["high"].reset_index(drop=True)
    low = bars["low"].reset_index(drop=True)
    volume = bars["volume"].reset_index(drop=True)
    ot = pd.to_datetime(bars["open_time"], utc=True).reset_index(drop=True)

    # ── 1h indicators ─────────────────────────────────────────────────────────
    rsi_1h = rsi(close, p.rsi_period)
    atr_1h = atr(high, low, close, p.atr_period)
    vol_ma = volume.rolling(p.vol_window, min_periods=1).mean()
    vol_ok = volume >= (p.vol_ratio_min * vol_ma)

    # ── Daily trend filter (resample → indicators → lag one day) ──────────────
    daily_close = pd.Series(close.to_numpy(), index=pd.DatetimeIndex(ot)).resample("1D").last()
    d_fast = sma(daily_close, p.daily_sma_fast)
    d_slow = sma(daily_close, p.daily_sma_slow)
    d_trend_up = (daily_close > d_slow) & (d_fast > d_slow)

    # Lag by one day: day T uses the daily bar confirmed at close of T-1.
    d_trend_up_lag = d_trend_up.shift(1)
    d_fast_lag = d_fast.shift(1)

    # Map lagged daily values onto the 1h timeline (as-of forward fill).
    ot_index = pd.DatetimeIndex(ot)
    trend_up_1h = (
        d_trend_up_lag.reindex(ot_index, method="ffill").fillna(False).to_numpy(dtype=bool)
    )
    d_fast_1h = d_fast_lag.reindex(ot_index, method="ffill").to_numpy(dtype=float)

    # ── Entry: RSI dipped below oversold recently, now crosses back above recovery ─
    oversold = rsi_1h < p.oversold_level
    recovered = (rsi_1h >= p.recovery_level) & (rsi_1h.shift(1) < p.recovery_level)
    recent_oversold = (
        oversold.rolling(p.recovery_window, min_periods=1).max().shift(1).fillna(0) > 0
    )

    price_above_daily = pd.Series(close.to_numpy() > d_fast_1h, index=close.index).fillna(False)

    entries = (
        recovered.fillna(False)
        & recent_oversold
        & price_above_daily
        & vol_ok.fillna(False)
        & pd.Series(trend_up_1h, index=close.index)
    )

    return TrendPullbackSignals(
        entries=pd.Series(entries.to_numpy(dtype=bool), index=idx),
        atr_series=pd.Series(atr_1h.to_numpy(dtype=float), index=idx),
        trend_active=pd.Series(trend_up_1h, index=idx),
    )
