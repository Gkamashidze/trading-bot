"""Strategy base class and result DTO."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field


class StrategyResult(BaseModel):
    """Immutable result of running a strategy on a set of bars."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str
    symbol: str = "BTC/USDT"
    signal: str  # "BUY" | "SELL" | "HOLD"
    strength: float = Field(ge=0.0, le=1.0)
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    indicators: dict[str, float] = Field(default_factory=dict)
    bars_used: int = 0
    reason: str = ""


class StrategyBase(ABC):
    """Base class for all signal-generating strategies."""

    strategy_id: str
    min_bars_required: int

    @abstractmethod
    def compute(self, bars: pd.DataFrame) -> StrategyResult:
        """Compute a signal from historical OHLCV bars.

        bars: DataFrame with columns [open_time, close, high, low, open, volume],
              sorted oldest-first.
        """

    @abstractmethod
    def backtest_signals(self, bars: pd.DataFrame) -> pd.Series:
        """Return a Series of 'BUY'/'SELL'/'HOLD' for every bar (no lookahead).

        Signal at index i uses only data[0..i].
        The backtesting engine executes the trade at bar[i+1]'s open.
        """
