"""Sentiment / positioning contrarian strategies (non-price signals).

Every price-based strategy tested (MA, RSI, breakout, MACD, ATR pullback) has
failed to beat buy-and-hold out-of-sample on BTC and on ETFs. If an edge exists,
it is more likely in signals that are NOT in the price: crowd sentiment and
derivatives positioning. These strategies test that hypothesis.

They read extra columns merged onto the OHLCV bars (``fear_greed``,
``funding_rate``) — see scripts/download_signal_data.py. Signals are level-based
and trailing-only: a signal on bar i uses that bar's already-published value and
the engine executes at bar i+1's open (no look-ahead).

Both are long-only and NOT registered in the promotion pipeline — research only,
must clear the walk-forward bar first.
"""

from __future__ import annotations

import pandas as pd

from trading_bot.strategies.base import StrategyBase, StrategyResult
from trading_bot.strategies.indicators import sma


class FearGreedContrarianStrategy(StrategyBase):
    """Buy extreme fear, sell into greed (Fear & Greed index, 0-100).

    Hold from a fear reading (F&G <= buy_below) until greed (F&G >= sell_above).
    The classic "be greedy when others are fearful" rule, tested honestly.
    """

    strategy_id = "fear_greed_contrarian"

    def __init__(self, buy_below: float = 25.0, sell_above: float = 60.0) -> None:
        self.buy_below = buy_below
        self.sell_above = sell_above
        self.min_bars_required = 2

    def compute(self, bars: pd.DataFrame) -> StrategyResult:
        if "fear_greed" not in bars.columns or len(bars) < self.min_bars_required:
            return StrategyResult(strategy_id=self.strategy_id, signal="HOLD", strength=0.0)
        fng = bars["fear_greed"].iloc[-1]
        if pd.isna(fng):
            signal = "HOLD"
        elif fng <= self.buy_below:
            signal = "BUY"
        elif fng >= self.sell_above:
            signal = "SELL"
        else:
            signal = "HOLD"
        return StrategyResult(
            strategy_id=self.strategy_id,
            signal=signal,
            strength=0.6 if signal == "BUY" else 0.0,
            bars_used=len(bars),
        )

    def backtest_signals(self, bars: pd.DataFrame) -> pd.Series:
        signals = pd.Series("HOLD", index=bars.index, dtype=object)
        if "fear_greed" not in bars.columns:
            return signals
        fng = bars["fear_greed"]
        signals[fng <= self.buy_below] = "BUY"
        signals[fng >= self.sell_above] = "SELL"
        return signals


class FundingContrarianStrategy(StrategyBase):
    """Buy crowded shorts, sell crowded longs (perp funding rate).

    Very negative funding = shorts pay longs = bearish crowd, often a contrarian
    bottom. Very positive funding = crowded longs, often a local top. Long-only:
    enter when funding <= buy_below, exit when funding >= sell_above.
    """

    strategy_id = "funding_contrarian"

    def __init__(self, buy_below: float = 0.0, sell_above: float = 0.0003) -> None:
        self.buy_below = buy_below
        self.sell_above = sell_above
        self.min_bars_required = 2

    def compute(self, bars: pd.DataFrame) -> StrategyResult:
        if "funding_rate" not in bars.columns or len(bars) < self.min_bars_required:
            return StrategyResult(strategy_id=self.strategy_id, signal="HOLD", strength=0.0)
        rate = bars["funding_rate"].iloc[-1]
        if pd.isna(rate):
            signal = "HOLD"
        elif rate <= self.buy_below:
            signal = "BUY"
        elif rate >= self.sell_above:
            signal = "SELL"
        else:
            signal = "HOLD"
        return StrategyResult(
            strategy_id=self.strategy_id,
            signal=signal,
            strength=0.6 if signal == "BUY" else 0.0,
            bars_used=len(bars),
        )

    def backtest_signals(self, bars: pd.DataFrame) -> pd.Series:
        signals = pd.Series("HOLD", index=bars.index, dtype=object)
        if "funding_rate" not in bars.columns:
            return signals
        rate = bars["funding_rate"]
        signals[rate <= self.buy_below] = "BUY"
        signals[rate >= self.sell_above] = "SELL"
        return signals


class SentimentTrendHybridStrategy(StrategyBase):
    """Contrarian entry, trend-following exit.

    The pure contrarian exit (sell into greed / high funding) leaves most of a
    bull run on the table. This hybrid keeps the contrarian ENTRY (buy crowded
    shorts / extreme fear while price is above its MA) but exits only when the
    trend breaks (price < MA) — "buy the dip, then ride the trend".

    Uses ``funding_rate`` when present, else falls back to ``fear_greed``.
    """

    strategy_id = "sentiment_trend_hybrid"

    def __init__(
        self,
        funding_below: float = 0.0,
        fear_below: float = 30.0,
        exit_ma: int = 50,
    ) -> None:
        self.funding_below = funding_below
        self.fear_below = fear_below
        self.exit_ma = exit_ma
        self.min_bars_required = exit_ma + 2

    def _entry_mask(self, bars: pd.DataFrame) -> pd.Series:
        if "funding_rate" in bars.columns and bars["funding_rate"].notna().any():
            return bars["funding_rate"] <= self.funding_below
        if "fear_greed" in bars.columns:
            return bars["fear_greed"] <= self.fear_below
        return pd.Series(False, index=bars.index)

    def compute(self, bars: pd.DataFrame) -> StrategyResult:
        if len(bars) < self.min_bars_required:
            return StrategyResult(strategy_id=self.strategy_id, signal="HOLD", strength=0.0)
        closes = bars["close"].astype(float)
        ma = sma(closes, self.exit_ma)
        below_trend = float(closes.iloc[-1]) < float(ma.iloc[-1])
        entry = bool(self._entry_mask(bars).iloc[-1])
        above_trend = float(closes.iloc[-1]) >= float(ma.iloc[-1])
        if below_trend:
            signal = "SELL"
        elif entry and above_trend:
            signal = "BUY"
        else:
            signal = "HOLD"
        return StrategyResult(
            strategy_id=self.strategy_id,
            signal=signal,
            strength=0.6 if signal == "BUY" else 0.0,
            bars_used=len(bars),
        )

    def backtest_signals(self, bars: pd.DataFrame) -> pd.Series:
        signals = pd.Series("HOLD", index=bars.index, dtype=object)
        closes = bars["close"].astype(float)
        ma = sma(closes, self.exit_ma)
        entry = self._entry_mask(bars) & (closes >= ma) & ma.notna()
        exit_ = (closes < ma) & ma.notna()
        signals[entry] = "BUY"
        signals[exit_] = "SELL"  # trend exit dominates when both fire
        return signals
