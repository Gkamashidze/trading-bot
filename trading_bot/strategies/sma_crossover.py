"""SMA Crossover strategy — buy when fast SMA crosses above slow SMA."""

from __future__ import annotations

import pandas as pd

from trading_bot.strategies.base import StrategyBase, StrategyResult
from trading_bot.strategies.indicators import sma


class SmaCrossoverStrategy(StrategyBase):
    """Generate BUY on golden cross, SELL on death cross.

    Default: 20-day SMA (fast) vs 50-day SMA (slow).
    Signal fires on the bar where the crossover happens.
    Between crossovers: HOLD with trend bias reflected in strength.
    """

    strategy_id = "sma_crossover"

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        self.fast = fast
        self.slow = slow
        self.min_bars_required = slow + 2

    def compute(self, bars: pd.DataFrame) -> StrategyResult:
        closes = bars["close"].astype(float)
        n = len(closes)

        if n < self.min_bars_required:
            return StrategyResult(
                strategy_id=self.strategy_id,
                signal="HOLD",
                strength=0.0,
                bars_used=n,
                reason=f"insufficient data: need {self.min_bars_required} bars, got {n}",
            )

        fast_sma = sma(closes, self.fast)
        slow_sma = sma(closes, self.slow)

        fast_now = float(fast_sma.iloc[-1])
        slow_now = float(slow_sma.iloc[-1])
        fast_prev = float(fast_sma.iloc[-2])
        slow_prev = float(slow_sma.iloc[-2])

        gap_pct = abs(fast_now - slow_now) / slow_now

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        if crossed_up:
            signal = "BUY"
            strength = min(1.0, gap_pct * 20 + 0.5)
            reason = f"SMA{self.fast} crossed above SMA{self.slow} (golden cross)"
        elif crossed_down:
            signal = "SELL"
            strength = min(1.0, gap_pct * 20 + 0.5)
            reason = f"SMA{self.fast} crossed below SMA{self.slow} (death cross)"
        elif fast_now > slow_now:
            signal = "HOLD"
            strength = min(0.5, gap_pct * 8)
            reason = f"SMA{self.fast} > SMA{self.slow} — bullish trend, no fresh crossover"
        else:
            signal = "HOLD"
            strength = min(0.5, gap_pct * 8)
            reason = f"SMA{self.fast} < SMA{self.slow} — bearish trend, no fresh crossover"

        return StrategyResult(
            strategy_id=self.strategy_id,
            signal=signal,
            strength=round(strength, 3),
            bars_used=n,
            indicators={
                f"sma_{self.fast}": round(fast_now, 2),
                f"sma_{self.slow}": round(slow_now, 2),
                "gap_pct": round(gap_pct * 100, 3),
            },
            reason=reason,
        )
