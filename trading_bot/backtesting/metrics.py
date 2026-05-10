"""Performance metrics — pure functions, no side effects."""

from __future__ import annotations

import math

import pandas as pd

from trading_bot.backtesting.result import BacktestMetrics


def compute_metrics(
    equity_curve: pd.Series,
    trade_returns: list[float],
    in_position: pd.Series,
    annual_trading_days: int = 365,
) -> BacktestMetrics:
    n_bars = len(equity_curve)
    initial = float(equity_curve.iloc[0])
    final = float(equity_curve.iloc[-1])

    total_return = (final / initial - 1) * 100.0

    years = n_bars / annual_trading_days
    if years > 0 and final > 0 and initial > 0:
        cagr = ((final / initial) ** (1.0 / years) - 1.0) * 100.0
    else:
        cagr = 0.0

    daily_returns = equity_curve.pct_change().dropna()
    std = float(daily_returns.std())
    mean = float(daily_returns.mean())

    sharpe = (mean / std) * math.sqrt(annual_trading_days) if std > 0 else 0.0

    downside = daily_returns[daily_returns < 0]
    down_std = float(downside.std())
    sortino = (mean / down_std) * math.sqrt(annual_trading_days) if down_std > 0 else 0.0

    rolling_max = equity_curve.cummax()
    drawdown = (equity_curve - rolling_max) / rolling_max
    max_dd = float(drawdown.min()) * 100.0

    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0
    recovery = total_return / abs(max_dd) if max_dd < 0 else 0.0

    n_trades = len(trade_returns)
    wins = [r for r in trade_returns if r > 0]
    losses = [r for r in trade_returns if r <= 0]

    win_rate = len(wins) / n_trades * 100.0 if n_trades > 0 else 0.0
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    avg_win = sum(wins) / len(wins) * 100.0 if wins else 0.0
    avg_loss = sum(losses) / len(losses) * 100.0 if losses else 0.0

    win_rate_frac = len(wins) / n_trades if n_trades > 0 else 0.0
    loss_rate_frac = 1.0 - win_rate_frac
    expectancy = win_rate_frac * avg_win + loss_rate_frac * avg_loss

    max_consec = 0
    cur_consec = 0
    for r in trade_returns:
        if r <= 0:
            cur_consec += 1
            max_consec = max(max_consec, cur_consec)
        else:
            cur_consec = 0

    exposure_pct = float(in_position.mean()) * 100.0

    return BacktestMetrics(
        total_return_pct=round(total_return, 2),
        cagr_pct=round(cagr, 2),
        sharpe_ratio=round(sharpe, 3),
        sortino_ratio=round(sortino, 3),
        calmar_ratio=round(calmar, 3),
        max_drawdown_pct=round(max_dd, 2),
        win_rate=round(win_rate, 1),
        profit_factor=round(profit_factor, 3),
        expectancy=round(expectancy, 3),
        total_trades=n_trades,
        winning_trades=len(wins),
        losing_trades=len(losses),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        max_consecutive_losses=max_consec,
        exposure_time_pct=round(exposure_pct, 1),
        recovery_factor=round(recovery, 3),
    )
