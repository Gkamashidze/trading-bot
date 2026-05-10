"""Backtesting runner — loads bars, runs all registered strategies, caches results."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.result import BacktestResult
from trading_bot.observability.logging import get_logger
from trading_bot.strategies.runner import _STRATEGIES, _load_bars

log = get_logger(__name__)

_last_results: list[BacktestResult] = []
_last_computed_at: datetime | None = None


def get_latest_backtest() -> list[BacktestResult]:
    return list(_last_results)


def get_last_backtest_at() -> datetime | None:
    return _last_computed_at


async def run_backtests() -> list[BacktestResult]:
    global _last_results, _last_computed_at

    from trading_bot.config import get_settings

    crypto = get_settings().trading.crypto
    config = BacktestConfig()
    engine = BacktestEngine(config)
    all_results: list[BacktestResult] = []

    for symbol in crypto.symbols:
        bars = _load_bars(symbol=symbol, max_bars=500)
        if bars is None or bars.empty:
            log.warning("backtest_skipped", symbol=symbol, reason="no bars available")
            continue

        for strategy in _STRATEGIES:
            try:
                result = engine.run(bars, strategy)
                result.symbol = symbol
                all_results.append(result)
                m = result.metrics
                log.info(
                    "backtest_complete",
                    symbol=symbol,
                    strategy=result.strategy_id,
                    bars=result.n_bars,
                    total_return_pct=m.total_return_pct,
                    sharpe=m.sharpe_ratio,
                    max_dd_pct=m.max_drawdown_pct,
                    trades=m.total_trades,
                )
            except Exception as e:
                log.error(
                    "backtest_error", symbol=symbol, strategy=strategy.strategy_id, error=str(e)
                )

    _last_results = all_results
    _last_computed_at = datetime.now(UTC)
    return all_results
