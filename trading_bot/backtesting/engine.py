"""Vectorized backtesting engine — long-only, bar-by-bar simulation.

Execution model:
  signal at bar[i]  →  trade executes at bar[i+1] open  (no lookahead)
  Entry: fill = open[i+1] * (1 + slippage)
  Exit:  fill = open[i+1] * (1 - slippage)
  Fee:   applied on gross investment / gross proceeds
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.metrics import compute_metrics
from trading_bot.backtesting.result import BacktestResult
from trading_bot.strategies.base import StrategyBase


class BacktestEngine:
    def __init__(self, config: BacktestConfig | None = None) -> None:
        self.config = config or BacktestConfig()

    def run(self, bars: pd.DataFrame, strategy: StrategyBase) -> BacktestResult:
        n = len(bars)
        if n < strategy.min_bars_required:
            raise ValueError(f"Backtest needs {strategy.min_bars_required} bars, got {n}")

        signals = strategy.backtest_signals(bars)
        signal_arr = signals.to_numpy()
        opens = bars["open"].to_numpy(dtype=float)
        closes = bars["close"].to_numpy(dtype=float)

        cfg = self.config
        cash = cfg.initial_capital
        units = 0.0
        position = 0
        entry_price = 0.0
        trade_returns: list[float] = []

        equity = np.empty(n, dtype=float)
        equity[0] = cash
        in_pos = np.zeros(n, dtype=bool)

        for i in range(1, n):
            sig = signal_arr[i - 1]

            if sig == "BUY" and position == 0:
                fill = opens[i] * (1.0 + cfg.slippage_rate)
                invest = cash * cfg.position_size_pct
                fee = invest * cfg.fee_rate
                units = (invest - fee) / fill
                cash -= invest
                position = 1
                entry_price = fill

            elif sig == "SELL" and position == 1:
                fill = opens[i] * (1.0 - cfg.slippage_rate)
                proceeds = units * fill
                fee = proceeds * cfg.fee_rate
                net = proceeds - fee
                trade_returns.append(net / (units * entry_price) - 1.0)
                cash += net
                units = 0.0
                position = 0

            in_pos[i] = position == 1
            equity[i] = cash + units * closes[i]

        if position == 1 and units > 0:
            fill = closes[-1] * (1.0 - cfg.slippage_rate)
            proceeds = units * fill
            fee = proceeds * cfg.fee_rate
            net = proceeds - fee
            trade_returns.append(net / (units * entry_price) - 1.0)
            cash += net
            equity[-1] = cash

        dates = bars["open_time"] if "open_time" in bars.columns else pd.RangeIndex(n)
        equity_s = pd.Series(equity, index=pd.DatetimeIndex(dates))
        in_pos_s = pd.Series(in_pos, index=pd.DatetimeIndex(dates))

        metrics = compute_metrics(
            equity_curve=equity_s,
            trade_returns=trade_returns,
            in_position=in_pos_s,
            annual_trading_days=cfg.annual_trading_days,
        )

        t_col: pd.Series = (
            bars["open_time"] if "open_time" in bars.columns else bars.index.to_series()
        )
        period_start = str(t_col.iloc[0])[:10]
        period_end = str(t_col.iloc[-1])[:10]

        return BacktestResult(
            strategy_id=strategy.strategy_id,
            symbol="BTC/USDT",  # overridden by caller (runner.py)
            config=cfg,
            metrics=metrics,
            equity_curve=equity_s,
            computed_at=datetime.now(UTC),
            n_bars=n,
            period_start=period_start,
            period_end=period_end,
        )
