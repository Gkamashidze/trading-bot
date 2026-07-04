"""Construct a GoLiveGate wired to live evidence and system state.

GoLiveGate's criteria were designed around static constructor params that
default to fail-closed values, and nothing ever instantiated it. This builder
sources those params from the evidence store, reconciler, backtest cache, and
feature-flag store so evaluate() reflects reality, and it enforces the Gate 0
minimums (≥30 paper days, ≥100 completed round-trips).

Best-effort: any data source that is unavailable leaves its param at the
fail-closed default, so the corresponding criterion fails rather than passing
on missing data.
"""

from __future__ import annotations

from pathlib import Path

from trading_bot.go_live.gate import GoLiveGate
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

MIN_PAPER_DAYS = 30
MIN_ROUND_TRIPS = 100

# Expected rollback runbook (Gate 0 requires a documented rollback plan).
_ROLLBACK_RUNBOOK = Path("trading_bot/docs/runbooks/deployment-rollback.md")


def _rollback_runbook_exists() -> bool:
    return _ROLLBACK_RUNBOOK.exists()


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


async def _paper_backtest_means(
    pool: object,
) -> tuple[float | None, float | None, float | None, float | None]:
    """Return (paper_win, paper_dd, backtest_win, backtest_dd) means across strategies."""
    from trading_bot.backtesting.runner import get_latest_backtest
    from trading_bot.promotion.pipeline import collect_strategy_metrics
    from trading_bot.strategies.registry import get_strategy_registry

    paper_wins: list[float] = []
    paper_dds: list[float] = []
    for entry in get_strategy_registry().all_entries():
        metrics = await collect_strategy_metrics(entry.strategy_id, pool)
        if metrics is not None:
            paper_wins.append(metrics.win_rate)
            paper_dds.append(metrics.max_drawdown_pct)

    bt_wins: list[float] = []
    bt_dds: list[float] = []
    for bt in get_latest_backtest():
        bt_wins.append(bt.metrics.win_rate)
        bt_dds.append(bt.metrics.max_drawdown_pct)

    return _mean(paper_wins), _mean(paper_dds), _mean(bt_wins), _mean(bt_dds)


async def _evidence_paper_stats(pool: object) -> tuple[int, int]:
    """Return (paper_days_observed, round_trip_count) from the evidence store."""
    from trading_bot.evidence import get_current_session_id, get_evidence_store

    try:
        store = get_evidence_store()
    except RuntimeError:
        return 0, 0
    session_id = get_current_session_id()
    if session_id is None:
        return 0, 0
    daily = await store.list_daily_summaries(session_id, limit=365)
    round_trips = await store.count_round_trips(session_id)
    return len(daily), round_trips


async def build_go_live_gate(pool: object) -> GoLiveGate:
    """Build a GoLiveGate with all params sourced from live evidence + state."""
    from trading_bot.database.audit_log import PostgresAuditLog
    from trading_bot.execution.paper import PaperExchange
    from trading_bot.feature_flags.store import get_default_store
    from trading_bot.oms.reconciler import ReconciliationSeverity, get_reconciler

    paper_days, round_trips = await _evidence_paper_stats(pool)

    reconciler = get_reconciler()
    recon_clean = (
        reconciler is not None
        and reconciler.last_report is not None
        and reconciler.last_report.severity == ReconciliationSeverity.OK
    )

    paper_win, paper_dd, bt_win, bt_dd = await _paper_backtest_means(pool)

    gate = GoLiveGate(
        audit_log=PostgresAuditLog(pool),
        exchange=PaperExchange(),
        feature_flags=get_default_store(),
        pool=pool,
        reconciler_last_run_clean=recon_clean,
        paper_trading_days=paper_days,
        paper_round_trips=round_trips,
        min_paper_days=MIN_PAPER_DAYS,
        min_round_trips=MIN_ROUND_TRIPS,
        paper_win_rate=paper_win,
        paper_drawdown_pct=paper_dd,
        backtest_win_rate=bt_win,
        backtest_drawdown_pct=bt_dd,
        rollback_runbook_exists=_rollback_runbook_exists(),
    )
    await gate.load_latest_approval()
    log.info(
        "go_live_gate_built",
        paper_days=paper_days,
        round_trips=round_trips,
        reconciler_clean=recon_clean,
    )
    return gate
