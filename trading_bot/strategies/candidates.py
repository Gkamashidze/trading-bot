"""Research candidate strategies under out-of-sample evaluation.

These are NOT production strategies and are NOT registered in the promotion
pipeline. Each must first clear the walk-forward bar (beat buy-and-hold OOS,
see scripts/run_walk_forward.py) before it earns a place in runner.py.

All signals are trailing-only (no look-ahead): a signal at bar i uses data ≤ i,
and the engine executes it at bar i+1's open.
"""

from __future__ import annotations

import pandas as pd

from trading_bot.strategies.base import StrategyBase, StrategyResult
from trading_bot.strategies.indicators import sma


class TrendFilterStrategy(StrategyBase):
    """Regime filter: hold the asset while price is above its SMA, cash below it.

    The classic "don't fight the trend / sit out bear markets" rule. On a market
    with severe drawdowns this can beat buy-and-hold on a risk-adjusted basis by
    avoiding the worst declines, at the cost of missing sharp V-shaped recoveries.
    """

    strategy_id = "trend_filter"

    def __init__(self, period: int = 1200) -> None:
        self.period = period
        self.min_bars_required = period + 2

    def compute(self, bars: pd.DataFrame) -> StrategyResult:
        closes = bars["close"].astype(float)
        if len(closes) < self.min_bars_required:
            return StrategyResult(strategy_id=self.strategy_id, signal="HOLD", strength=0.0)
        ma = sma(closes, self.period)
        above = float(closes.iloc[-1]) > float(ma.iloc[-1])
        return StrategyResult(
            strategy_id=self.strategy_id,
            signal="BUY" if above else "SELL",
            strength=0.6 if above else 0.0,
            bars_used=len(closes),
        )

    def backtest_signals(self, bars: pd.DataFrame) -> pd.Series:
        closes = bars["close"].astype(float)
        ma = sma(closes, self.period)
        above = closes > ma
        prev = above.shift(1)
        signals = pd.Series("HOLD", index=bars.index, dtype=object)
        signals[ma.notna() & above & ~prev.fillna(False)] = "BUY"
        signals[ma.notna() & ~above & prev.fillna(False)] = "SELL"
        return signals


class DonchianBreakoutStrategy(StrategyBase):
    """Turtle-style breakout: buy an N-bar high, exit on an M-bar low."""

    strategy_id = "donchian_breakout"

    def __init__(self, entry: int = 480, exit_period: int = 240) -> None:
        self.entry = entry
        self.exit_period = exit_period
        self.min_bars_required = max(entry, exit_period) + 2

    def compute(self, bars: pd.DataFrame) -> StrategyResult:
        return StrategyResult(strategy_id=self.strategy_id, signal="HOLD", strength=0.0)

    def backtest_signals(self, bars: pd.DataFrame) -> pd.Series:
        high = bars["high"].astype(float)
        low = bars["low"].astype(float)
        close = bars["close"].astype(float)
        # Prior-window extremes (shift(1) excludes the current bar → no look-ahead).
        entry_high = high.rolling(self.entry).max().shift(1)
        exit_low = low.rolling(self.exit_period).min().shift(1)
        signals = pd.Series("HOLD", index=bars.index, dtype=object)
        signals[entry_high.notna() & (close >= entry_high)] = "BUY"
        signals[exit_low.notna() & (close <= exit_low)] = "SELL"
        return signals


class MacdStrategy(StrategyBase):
    """MACD crossover: buy when the MACD line crosses above its signal line."""

    strategy_id = "macd"

    def __init__(self, fast: int = 24, slow: int = 52, signal: int = 18) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        self.fast = fast
        self.slow = slow
        self.signal = signal
        self.min_bars_required = slow + signal + 2

    def compute(self, bars: pd.DataFrame) -> StrategyResult:
        return StrategyResult(strategy_id=self.strategy_id, signal="HOLD", strength=0.0)

    def backtest_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["close"].astype(float)
        ema_fast = close.ewm(span=self.fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=self.signal, adjust=False).mean()
        prev_macd = macd.shift(1)
        prev_signal = macd_signal.shift(1)
        cross_up = (prev_macd <= prev_signal) & (macd > macd_signal)
        cross_down = (prev_macd >= prev_signal) & (macd < macd_signal)
        signals = pd.Series("HOLD", index=bars.index, dtype=object)
        signals[cross_up] = "BUY"
        signals[cross_down] = "SELL"
        return signals
