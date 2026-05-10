"""Backtesting result types — metrics DTO and full result."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from trading_bot.backtesting.config import BacktestConfig


@dataclass(frozen=True)
class BacktestMetrics:
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown_pct: float
    win_rate: float
    profit_factor: float
    expectancy: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win_pct: float
    avg_loss_pct: float
    max_consecutive_losses: int
    exposure_time_pct: float
    recovery_factor: float


@dataclass
class BacktestResult:
    strategy_id: str
    config: BacktestConfig
    metrics: BacktestMetrics
    equity_curve: pd.Series
    computed_at: datetime
    n_bars: int
    period_start: str
    period_end: str
