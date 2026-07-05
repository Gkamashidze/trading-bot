"""Unit tests for non-price sentiment/positioning strategies."""

from __future__ import annotations

import pandas as pd

from trading_bot.strategies.sentiment import (
    FearGreedContrarianStrategy,
    FundingContrarianStrategy,
    SentimentTrendHybridStrategy,
)


def _bars(close: list[float], **cols: list[float]) -> pd.DataFrame:
    n = len(close)
    data = {
        "open_time": pd.date_range("2022-01-01", periods=n, freq="1D", tz="UTC"),
        "open": close,
        "high": [c * 1.01 for c in close],
        "low": [c * 0.99 for c in close],
        "close": close,
        "volume": [100.0] * n,
    }
    data.update(cols)
    return pd.DataFrame(data)


class TestFearGreedContrarian:
    def test_buys_extreme_fear_sells_greed(self) -> None:
        bars = _bars([100.0] * 4, fear_greed=[15.0, 50.0, 70.0, 50.0])
        sig = FearGreedContrarianStrategy(buy_below=25, sell_above=60).backtest_signals(bars)
        assert sig.iloc[0] == "BUY"  # F&G 15 ≤ 25
        assert sig.iloc[1] == "HOLD"  # neutral
        assert sig.iloc[2] == "SELL"  # F&G 70 ≥ 60
        assert sig.iloc[3] == "HOLD"

    def test_nan_fear_greed_is_hold(self) -> None:
        bars = _bars([100.0, 100.0], fear_greed=[float("nan"), 10.0])
        sig = FearGreedContrarianStrategy().backtest_signals(bars)
        assert sig.iloc[0] == "HOLD"
        assert sig.iloc[1] == "BUY"

    def test_missing_column_is_all_hold(self) -> None:
        bars = _bars([100.0, 100.0])
        sig = FearGreedContrarianStrategy().backtest_signals(bars)
        assert (sig == "HOLD").all()


class TestFundingContrarian:
    def test_buys_negative_funding_sells_high(self) -> None:
        bars = _bars([100.0] * 3, funding_rate=[-0.0005, 0.0001, 0.0006])
        sig = FundingContrarianStrategy(buy_below=0.0, sell_above=0.0003).backtest_signals(bars)
        assert sig.iloc[0] == "BUY"  # negative funding
        assert sig.iloc[1] == "HOLD"
        assert sig.iloc[2] == "SELL"  # 0.0006 ≥ 0.0003


class TestSentimentTrendHybrid:
    def test_entry_requires_above_trend(self) -> None:
        # Rising price so it's above its short MA; negative funding → entry.
        close = [100.0 + i for i in range(10)]
        funding = [-0.001] * 10  # always "crowded shorts"
        bars = _bars(close, funding_rate=funding)
        sig = SentimentTrendHybridStrategy(funding_below=0.0, exit_ma=3).backtest_signals(bars)
        # Once the MA warms up and price is above it, entries fire.
        assert (sig == "BUY").any()

    def test_exit_on_trend_break(self) -> None:
        # Price ramps up then crashes below its MA → SELL appears.
        close = [100.0 + i for i in range(8)] + [50.0, 40.0, 30.0]
        funding = [-0.001] * 11
        bars = _bars(close, funding_rate=funding)
        sig = SentimentTrendHybridStrategy(funding_below=0.0, exit_ma=3).backtest_signals(bars)
        assert (sig == "SELL").any()

    def test_falls_back_to_fear_greed_without_funding(self) -> None:
        close = [100.0 + i for i in range(10)]
        bars = _bars(close, fear_greed=[10.0] * 10)  # no funding column
        sig = SentimentTrendHybridStrategy(fear_below=30, exit_ma=3).backtest_signals(bars)
        assert (sig == "BUY").any()  # fear-based entry via fallback
