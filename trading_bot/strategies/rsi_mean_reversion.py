"""RSI Mean Reversion strategy — buy oversold, sell overbought."""

from __future__ import annotations

import pandas as pd

from trading_bot.strategies.base import StrategyBase, StrategyResult
from trading_bot.strategies.indicators import rsi as compute_rsi


class RsiMeanReversionStrategy(StrategyBase):
    """Generate BUY when RSI is below `oversold`, SELL when above `overbought`.

    Default: RSI(14), oversold=30, overbought=70.
    HOLD when RSI is in the neutral zone between the thresholds.
    """

    strategy_id = "rsi_mean_reversion"

    def __init__(
        self,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
    ) -> None:
        if oversold >= overbought:
            raise ValueError(f"oversold ({oversold}) must be < overbought ({overbought})")
        self.period = period
        self.oversold = oversold
        self.overbought = overbought
        self.min_bars_required = period + 2

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

        rsi_series = compute_rsi(closes, self.period)
        rsi_now = float(rsi_series.iloc[-1])

        if rsi_now <= self.oversold:
            signal = "BUY"
            # How far into the oversold zone (0 RSI = max strength)
            strength = min(1.0, (self.oversold - rsi_now) / self.oversold + 0.4)
            reason = f"RSI {rsi_now:.1f} ≤ {self.oversold} — oversold"
        elif rsi_now >= self.overbought:
            signal = "SELL"
            # How far into the overbought zone (100 RSI = max strength)
            strength = min(1.0, (rsi_now - self.overbought) / (100.0 - self.overbought) + 0.4)
            reason = f"RSI {rsi_now:.1f} ≥ {self.overbought} — overbought"
        else:
            signal = "HOLD"
            strength = 0.0
            mid = (self.oversold + self.overbought) / 2
            if rsi_now >= mid:
                reason = f"RSI {rsi_now:.1f} — neutral zone (mildly bullish)"
            else:
                reason = f"RSI {rsi_now:.1f} — neutral zone (mildly bearish)"

        return StrategyResult(
            strategy_id=self.strategy_id,
            signal=signal,
            strength=round(strength, 3),
            bars_used=n,
            indicators={"rsi": round(rsi_now, 2)},
            reason=reason,
        )

    def backtest_signals(self, bars: pd.DataFrame) -> pd.Series:
        closes = bars["close"].astype(float)
        rsi_series = compute_rsi(closes, self.period)

        signals = pd.Series("HOLD", index=bars.index, dtype=object)
        valid = rsi_series.notna()

        signals[valid & (rsi_series <= self.oversold)] = "BUY"
        signals[valid & (rsi_series >= self.overbought)] = "SELL"
        return signals
