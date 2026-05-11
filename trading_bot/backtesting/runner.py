"""Backtesting runner — loads bars, runs all registered strategies, caches results.

Data lineage enforcement:
    Every backtest run is tied to a dataset_snapshot_id registered in the
    LineageStore.  When a symbol has no snapshot (e.g. bars predate lineage
    tracking, or the in-memory store was cleared on restart), a snapshot is
    auto-registered from the loaded bars' metadata so backtests remain
    reproducible without requiring an explicit registration step.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.result import BacktestResult
from trading_bot.core.models import DataLineage
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
    snapshots = [s for s in lineage_store.all_snapshots() if s.lineage.symbol == symbol]
    if not snapshots:
        return None
    # Return the snapshot with the most recent created_at
    return max(snapshots, key=lambda s: s.created_at).snapshot_id


def _auto_register_snapshot(
    symbol: str,
    timeframe: str,
    exchange: str,
    bars: pd.DataFrame,
    lineage_store: LineageStore,
) -> str:
    """Register a deterministic snapshot derived from loaded bars metadata.

    Used when no explicit snapshot exists — covers data backfilled before
    lineage tracking and recovers from in-memory store loss on restart.
    Idempotent: identical bars produce the same snapshot ID.
    """
    symbol_safe = symbol.replace("/", "_").replace(":", "_")
    last_ts = pd.to_datetime(bars["open_time"].max(), utc=True).to_pydatetime()
    lineage = DataLineage(
        source=f"{exchange}.fetch_ohlcv",
        fetched_at=last_ts,
        row_count=len(bars),
        provider=exchange,
        exchange=exchange.upper(),
        symbol=symbol,
        timeframe=timeframe,
        storage_path=f"{exchange}/{symbol_safe}/{timeframe}",
    )
    return lineage_store.create_snapshot(lineage)


async def run_backtests(
    require_lineage: bool = True,
) -> list[BacktestResult]:
    """Run backtests for all registered strategies across all configured symbols.

    Args:
        require_lineage: If True (default), auto-registers a snapshot derived
            from loaded bars when none exists, so results remain traceable.
            Set to False only in tests where snapshot tracking is irrelevant
            and an empty `dataset_snapshot_id` is acceptable.
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
                snapshot_id = _auto_register_snapshot(
                    symbol=symbol,
                    timeframe=crypto.timeframes[0],
                    exchange=crypto.exchange,
                    bars=bars,
                    lineage_store=lineage_store,
                )
                log.info(
                    "backtest_auto_snapshot_registered",
                    symbol=symbol,
                    snapshot_id=snapshot_id[:12],
                )
            else:
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
