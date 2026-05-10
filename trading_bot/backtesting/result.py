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
    # Transaction cost breakdown (new)
    total_fees_paid: float = 0.0  # sum of all fees in quote currency
    total_slippage_cost: float = 0.0  # sum of all spread + impact costs
    gross_total_return_pct: float = 0.0  # return BEFORE fees/slippage
    net_total_return_pct: float = 0.0  # return AFTER fees/slippage (= total_return_pct)
    partial_fills: int = 0  # number of partial fill events
    rejected_orders: int = 0  # number of stale-quote rejections


@dataclass
class BacktestResult:
    strategy_id: str
    symbol: str
    config: BacktestConfig
    metrics: BacktestMetrics
    equity_curve: pd.Series
    computed_at: datetime
    n_bars: int
    period_start: str
    period_end: str
    # Data lineage: snapshot ID that was used to produce this backtest result.
    # Must be a valid ID registered in LineageStore or equivalent.
    # Empty string only when lineage is explicitly waived (e.g. synthetic test data).
    dataset_snapshot_id: str = ""
