"""Walk-forward / out-of-sample backtest harness.

Textbook backtests optimise parameters on the same data they report on — that
is in-sample overfitting and proves nothing. This harness answers the honest
question: *does a strategy have edge on data it never saw during tuning?*

Method (no look-ahead):
1. Slide a train window over history. On each train window, grid-search the
   strategy parameters (best in-sample Sharpe, with a minimum-trade floor).
2. Apply those parameters to the *next* (out-of-sample) test window only.
3. Concatenate every test window's signals — each segment tuned solely on data
   that preceded it — into one composite signal series.
4. Run the existing BacktestEngine once over the OOS span with that composite
   series, so fills/fees/slippage compound continuously with no stitching
   artifacts.
5. Compare the OOS equity curve against buy-and-hold over the same span.

If the OOS result loses to buy-and-hold after costs, the strategy has no
demonstrated edge — and this harness will say so.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.metrics import compute_metrics
from trading_bot.backtesting.result import BacktestMetrics
from trading_bot.observability.logging import get_logger
from trading_bot.strategies.base import StrategyBase, StrategyResult

log = get_logger(__name__)

StrategyFactory = Callable[[dict[str, Any]], StrategyBase]

_MIN_TRAIN_TRADES = 5  # a param set must trade at least this often in-sample


class PrecomputedSignalStrategy(StrategyBase):
    """Wraps a precomputed BUY/SELL/HOLD series so the engine can execute it."""

    strategy_id = "walk_forward_composite"

    def __init__(self, signals: pd.Series) -> None:
        self._signals = signals.reset_index(drop=True)
        self.min_bars_required = 2

    def compute(self, bars: pd.DataFrame) -> StrategyResult:  # pragma: no cover - unused
        return StrategyResult(strategy_id=self.strategy_id, signal="HOLD", strength=0.0)

    def backtest_signals(self, bars: pd.DataFrame) -> pd.Series:
        return self._signals.reindex(range(len(bars)), fill_value="HOLD")


@dataclass(frozen=True)
class WalkForwardWindow:
    """One train→test step of the walk-forward."""

    index: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    best_params: dict[str, Any]
    train_sharpe: float


@dataclass(frozen=True)
class WalkForwardResult:
    """Full out-of-sample result plus its buy-and-hold benchmark."""

    strategy_id: str
    symbol: str
    windows: list[WalkForwardWindow]
    oos_metrics: BacktestMetrics
    benchmark_metrics: BacktestMetrics
    oos_equity_curve: pd.Series
    benchmark_equity_curve: pd.Series
    oos_start: str
    oos_end: str
    beats_benchmark: bool


def _optimise_params(
    train_bars: pd.DataFrame,
    factory: StrategyFactory,
    param_grid: Sequence[dict[str, Any]],
    config: BacktestConfig,
    min_train_trades: int = _MIN_TRAIN_TRADES,
) -> tuple[dict[str, Any], float]:
    """Return the (params, in-sample Sharpe) with the best Sharpe on the train window.

    A param set must produce at least ``min_train_trades`` trades to be eligible —
    otherwise a strategy that barely trades can post a misleadingly high Sharpe.
    Falls back to the first grid entry if nothing qualifies.
    """
    engine = BacktestEngine(config)
    best_params = dict(param_grid[0])
    best_sharpe = float("-inf")
    found = False

    for params in param_grid:
        strategy = factory(params)
        if len(train_bars) < strategy.min_bars_required:
            continue
        try:
            result = engine.run(train_bars, strategy)
        except Exception:  # noqa: S112 — a degenerate param combo, just skip it
            continue
        m = result.metrics
        if m.total_trades < min_train_trades:
            continue
        if m.sharpe_ratio > best_sharpe:
            best_sharpe = m.sharpe_ratio
            best_params = dict(params)
            found = True

    return best_params, (best_sharpe if found else 0.0)


def _buy_and_hold(bars: pd.DataFrame, config: BacktestConfig) -> tuple[BacktestMetrics, pd.Series]:
    """Buy at the first open (paying one fee), hold to the last close."""
    opens = bars["open"].astype(float).to_numpy()
    closes = bars["close"].astype(float).to_numpy()
    entry = opens[0]
    units = (config.initial_capital * (1.0 - config.fee_rate)) / entry
    equity = pd.Series(
        units * closes,
        index=pd.DatetimeIndex(bars["open_time"]),
    )
    trade_return = float(closes[-1] / entry - 1.0)
    in_pos = pd.Series(True, index=equity.index)
    metrics = compute_metrics(
        equity_curve=equity,
        trade_returns=[trade_return],
        in_position=in_pos,
        annual_trading_days=config.annual_trading_days,
    )
    return metrics, equity


def run_walk_forward(
    bars: pd.DataFrame,
    *,
    strategy_id: str,
    symbol: str,
    factory: StrategyFactory,
    param_grid: Sequence[dict[str, Any]],
    train_bars: int,
    test_bars: int,
    config: BacktestConfig | None = None,
    min_train_trades: int = _MIN_TRAIN_TRADES,
) -> WalkForwardResult:
    """Run a rolling walk-forward and return the honest OOS result vs buy-and-hold."""
    cfg = config or BacktestConfig()
    data = bars.sort_values("open_time").reset_index(drop=True)
    n = len(data)
    if n <= train_bars + test_bars:
        raise ValueError(f"need > {train_bars + test_bars} bars for walk-forward, got {n}")

    composite: list[str] = ["HOLD"] * n
    windows: list[WalkForwardWindow] = []

    idx = 0
    p = train_bars
    while p + test_bars <= n:
        train_slice = data.iloc[p - train_bars : p]
        best_params, train_sharpe = _optimise_params(
            train_slice, factory, param_grid, cfg, min_train_trades
        )

        # Signals computed on full history (trailing indicators → no look-ahead),
        # then sliced to this test segment only.
        seg_signals = factory(best_params).backtest_signals(data)
        test_end = min(p + test_bars, n)
        composite[p:test_end] = [str(s) for s in seg_signals.iloc[p:test_end].tolist()]

        windows.append(
            WalkForwardWindow(
                index=idx,
                train_start=str(data.iloc[p - train_bars]["open_time"])[:16],
                train_end=str(data.iloc[p - 1]["open_time"])[:16],
                test_start=str(data.iloc[p]["open_time"])[:16],
                test_end=str(data.iloc[test_end - 1]["open_time"])[:16],
                best_params=best_params,
                train_sharpe=round(train_sharpe, 3),
            )
        )
        idx += 1
        p += test_bars

    # Out-of-sample span = everything from the first test bar onward.
    oos = data.iloc[train_bars:].reset_index(drop=True)
    oos_signals = pd.Series(composite[train_bars:])

    engine = BacktestEngine(cfg)
    oos_result = engine.run(oos, PrecomputedSignalStrategy(oos_signals))
    bench_metrics, bench_equity = _buy_and_hold(oos, cfg)

    beats = oos_result.metrics.net_total_return_pct > bench_metrics.total_return_pct

    log.info(
        "walk_forward_complete",
        strategy_id=strategy_id,
        windows=len(windows),
        oos_return_pct=oos_result.metrics.net_total_return_pct,
        benchmark_return_pct=bench_metrics.total_return_pct,
        beats_benchmark=beats,
    )

    return WalkForwardResult(
        strategy_id=strategy_id,
        symbol=symbol,
        windows=windows,
        oos_metrics=oos_result.metrics,
        benchmark_metrics=bench_metrics,
        oos_equity_curve=oos_result.equity_curve,
        benchmark_equity_curve=bench_equity,
        oos_start=str(oos.iloc[0]["open_time"])[:16],
        oos_end=str(oos.iloc[-1]["open_time"])[:16],
        beats_benchmark=beats,
    )
