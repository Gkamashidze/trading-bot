"""Backtesting runner — loads bars, runs all registered strategies, caches results.

Data lineage enforcement:
    Every backtest run must have a valid dataset_snapshot_id registered in the
    LineageStore.  Runs without a valid snapshot ID are rejected.  This ensures
    all BacktestResult objects are traceable to the exact data they used.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.result import BacktestResult
from trading_bot.data.lineage import LineageStore, get_lineage_store
from trading_bot.observability.logging import get_logger
from trading_bot.strategies.runner import _STRATEGIES, _load_bars

log = get_logger(__name__)

_last_results: list[BacktestResult] = []
_last_computed_at: datetime | None = None


class LineageError(Exception):
    """Raised when a backtest is attempted without valid data lineage."""


def get_latest_backtest() -> list[BacktestResult]:
    return list(_last_results)


def get_last_backtest_at() -> datetime | None:
    return _last_computed_at


def _resolve_snapshot_id(symbol: str, lineage_store: LineageStore) -> str | None:
    """Return the most recent snapshot ID for `symbol`, or None if none registered."""
    snapshots = [
        s for s in lineage_store.all_snapshots() if s.lineage.symbol == symbol
    ]
    if not snapshots:
        return None
    # Return the snapshot with the most recent created_at
    return max(snapshots, key=lambda s: s.created_at).snapshot_id


async def run_backtests(
    require_lineage: bool = True,
) -> list[BacktestResult]:
    """Run backtests for all registered strategies across all configured symbols.

    Args:
        require_lineage: If True (default), raises LineageError when no valid
            dataset snapshot exists for a symbol.  Set to False only in tests
            that use synthetic data with no lineage store entry.
    """
    global _last_results, _last_computed_at

    from trading_bot.config import get_settings

    crypto = get_settings().trading.crypto
    config = BacktestConfig()
    engine = BacktestEngine(config)
    lineage_store = get_lineage_store()
    all_results: list[BacktestResult] = []

    for symbol in crypto.symbols:
        bars = _load_bars(symbol=symbol, max_bars=500)
        if bars is None or bars.empty:
            log.warning("backtest_skipped", symbol=symbol, reason="no bars available")
            continue

        # ── Lineage check ────────────────────────────────────────────────────
        snapshot_id = _resolve_snapshot_id(symbol, lineage_store)
        if snapshot_id is None:
            if require_lineage:
                raise LineageError(
                    f"No dataset snapshot registered for symbol '{symbol}'. "
                    "Register a DataLineage snapshot via get_lineage_store().create_snapshot() "
                    "before running backtests."
                )
            snapshot_id = ""
            log.warning(
                "backtest_no_lineage",
                symbol=symbol,
                note="lineage not required — proceeding with empty snapshot_id",
            )

        for strategy in _STRATEGIES:
            try:
                result = engine.run(bars, strategy, dataset_snapshot_id=snapshot_id)
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
                    dataset_snapshot_id=snapshot_id,
                )
            except Exception as e:
                log.error(
                    "backtest_error", symbol=symbol, strategy=strategy.strategy_id, error=str(e)
                )

    _last_results = all_results
    _last_computed_at = datetime.now(UTC)
    return all_results
