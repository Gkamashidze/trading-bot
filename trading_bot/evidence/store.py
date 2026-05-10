"""Paper Testing Evidence Store — durable append-only evidence for paper sessions.

All writes are idempotent via ON CONFLICT (idempotency_key) DO NOTHING.
All reads are non-mutating SELECT queries.
Audit log events are appended for every state-changing operation.

Session lifecycle:
  start_session()     — creates a new PaperSession row (status=running)
  get_current_session() — returns the single running session, or None
  end_session()       — sets status=completed and ended_at=NOW()
  resume_session()    — returns existing session when config hash matches

Startup logic:
  ensure_session()    — idempotent: resume if hash matches, else close+start new
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import asyncpg

from trading_bot.evidence.models import (
    AccountingEvidenceRecord,
    AlertIncidentEvidence,
    BacktestEvidenceSnapshot,
    DailyEvidenceSummary,
    PaperSession,
    PortfolioEvidenceSnapshot,
    ReconciliationEvidenceReport,
    SessionStatus,
    SignalEvidenceSnapshot,
    TCAEvidenceRecord,
    WeeklyEvidenceSummary,
)
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_NO_SESSION_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")


def _now() -> datetime:
    return datetime.now(UTC)


def _was_inserted(pg_result: Any) -> bool:
    """Return True if the asyncpg execute result indicates a row was inserted."""
    return bool(pg_result == "INSERT 0 1")


def _hash_config(snapshot: dict[str, Any]) -> str:
    """Stable SHA-256 of a config snapshot dict."""
    blob = json.dumps(snapshot, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


async def _audit(
    pool: asyncpg.Pool,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """Best-effort audit log append — failures are logged but not raised."""
    try:
        from trading_bot.database.audit_log import PostgresAuditLog

        audit = PostgresAuditLog(pool)
        await audit.append(event_type=event_type, payload=payload, actor="evidence_store")
    except Exception as exc:
        log.warning("evidence_audit_append_failed", event_type=event_type, error=str(exc))


class EvidenceStore:
    """Async evidence store backed by PostgreSQL.

    Requires an asyncpg pool initialised via init_pool().
    All writes are idempotent; duplicates are silently ignored.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    async def start_session(
        self,
        environment: str,
        config_snapshot: dict[str, Any],
        paper_capital: Decimal,
        symbols: list[str],
        strategies: list[str],
        git_commit: str | None = None,
        notes: str = "",
    ) -> PaperSession:
        """Create a new running PaperSession. Caller must check for existing first."""
        session = PaperSession(
            started_at=_now(),
            environment=environment,
            git_commit=git_commit,
            config_snapshot_hash=_hash_config(config_snapshot),
            paper_capital=paper_capital,
            symbols=symbols,
            strategies=strategies,
            status=SessionStatus.RUNNING,
            notes=notes,
        )
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO evidence_sessions (
                    session_id, started_at, ended_at, environment, git_commit,
                    config_snapshot_hash, paper_capital, symbols, strategies,
                    status, notes
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (session_id) DO NOTHING
                """,
                session.session_id,
                session.started_at,
                session.ended_at,
                session.environment,
                session.git_commit,
                session.config_snapshot_hash,
                session.paper_capital,
                json.dumps(session.symbols),
                json.dumps(session.strategies),
                session.status.value,
                session.notes,
            )
        log.info(
            "evidence_session_started",
            session_id=str(session.session_id),
            config_hash=session.config_snapshot_hash,
        )
        await _audit(
            self._pool,
            "evidence_session_started",
            {"session_id": str(session.session_id), "config_hash": session.config_snapshot_hash},
        )
        return session

    async def get_current_session(self) -> PaperSession | None:
        """Return the currently running session, or None."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT session_id, started_at, ended_at, environment, git_commit,
                       config_snapshot_hash, paper_capital, symbols, strategies, status, notes
                FROM evidence_sessions
                WHERE status = 'running'
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
        if row is None:
            return None
        return self._row_to_session(row)

    async def end_session(
        self, session_id: uuid.UUID, status: SessionStatus = SessionStatus.COMPLETED
    ) -> None:
        """Close a session by setting ended_at and status."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE evidence_sessions
                SET ended_at = $1, status = $2
                WHERE session_id = $3 AND status = 'running'
                """,
                _now(),
                status.value,
                session_id,
            )
        log.info("evidence_session_ended", session_id=str(session_id), status=status.value)
        await _audit(
            self._pool,
            "evidence_session_ended",
            {"session_id": str(session_id), "status": status.value},
        )

    async def ensure_session(
        self,
        environment: str,
        config_snapshot: dict[str, Any],
        paper_capital: Decimal,
        symbols: list[str],
        strategies: list[str],
        git_commit: str | None = None,
    ) -> PaperSession:
        """Idempotent startup helper.

        - If no running session → start new.
        - If running session with same config hash → resume (return it).
        - If running session with different config hash → close it, start new.
        """
        config_hash = _hash_config(config_snapshot)
        existing = await self.get_current_session()

        if existing is None:
            return await self.start_session(
                environment=environment,
                config_snapshot=config_snapshot,
                paper_capital=paper_capital,
                symbols=symbols,
                strategies=strategies,
                git_commit=git_commit,
                notes="auto-started on startup",
            )

        if existing.config_snapshot_hash == config_hash:
            log.info(
                "evidence_session_resumed",
                session_id=str(existing.session_id),
                config_hash=config_hash,
            )
            return existing

        # Config changed — close old, open new
        log.info(
            "evidence_session_config_changed",
            old_session=str(existing.session_id),
            old_hash=existing.config_snapshot_hash,
            new_hash=config_hash,
        )
        await self.end_session(existing.session_id, SessionStatus.COMPLETED)
        return await self.start_session(
            environment=environment,
            config_snapshot=config_snapshot,
            paper_capital=paper_capital,
            symbols=symbols,
            strategies=strategies,
            git_commit=git_commit,
            notes=f"config changed from {existing.config_snapshot_hash}",
        )

    # ------------------------------------------------------------------
    # B. Portfolio snapshots
    # ------------------------------------------------------------------

    async def insert_portfolio_snapshot(self, snap: PortfolioEvidenceSnapshot) -> bool:
        """Insert snapshot; returns False if idempotency key already exists."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO evidence_portfolio_snapshots (
                    snapshot_id, session_id, captured_at, cash_balance, total_equity,
                    daily_pnl, daily_drawdown_pct, positions, source, idempotency_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                snap.snapshot_id,
                snap.session_id,
                snap.captured_at,
                snap.cash_balance,
                snap.total_equity,
                snap.daily_pnl,
                snap.daily_drawdown_pct,
                json.dumps(snap.positions, default=str),
                snap.source.value,
                snap.idempotency_key,
            )
        inserted = _was_inserted(result)
        if inserted:
            log.debug(
                "evidence_portfolio_snapshot_inserted",
                session_id=str(snap.session_id),
                captured_at=snap.captured_at.isoformat(),
            )
        return inserted

    # ------------------------------------------------------------------
    # C. Signal snapshots
    # ------------------------------------------------------------------

    async def insert_signal_snapshot(self, snap: SignalEvidenceSnapshot) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO evidence_signal_snapshots (
                    snapshot_id, session_id, captured_at, symbol, strategy_id,
                    signal, strength, indicators, bars_used, market_context, idempotency_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                snap.snapshot_id,
                snap.session_id,
                snap.captured_at,
                snap.symbol,
                snap.strategy_id,
                snap.signal,
                snap.strength,
                json.dumps(snap.indicators, default=str),
                snap.bars_used,
                json.dumps(snap.market_context, default=str) if snap.market_context else None,
                snap.idempotency_key,
            )
        return _was_inserted(result)

    # ------------------------------------------------------------------
    # D. Backtest snapshots
    # ------------------------------------------------------------------

    async def insert_backtest_snapshot(self, snap: BacktestEvidenceSnapshot) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO evidence_backtest_snapshots (
                    snapshot_id, session_id, captured_at, strategy_id, symbol,
                    dataset_snapshot_ids, period_start, period_end, metrics, config,
                    gross_return_pct, net_return_pct, max_drawdown_pct, sharpe,
                    total_trades, idempotency_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                snap.snapshot_id,
                snap.session_id,
                snap.captured_at,
                snap.strategy_id,
                snap.symbol,
                json.dumps(snap.dataset_snapshot_ids),
                snap.period_start,
                snap.period_end,
                json.dumps(snap.metrics, default=str),
                json.dumps(snap.config, default=str),
                snap.gross_return_pct,
                snap.net_return_pct,
                snap.max_drawdown_pct,
                snap.sharpe,
                snap.total_trades,
                snap.idempotency_key,
            )
        return _was_inserted(result)

    # ------------------------------------------------------------------
    # E. TCA records
    # ------------------------------------------------------------------

    async def insert_tca_record(self, rec: TCAEvidenceRecord) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO evidence_tca_records (
                    record_id, session_id, captured_at, order_id, symbol, strategy_id,
                    side, signal_price, fill_price, quantity, fee_paid,
                    slippage_pct, slippage_usdt, latency_ms, quality_score,
                    outcome, retry_count, idempotency_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                rec.record_id,
                rec.session_id,
                rec.captured_at,
                rec.order_id,
                rec.symbol,
                rec.strategy_id,
                rec.side,
                rec.signal_price,
                rec.fill_price,
                rec.quantity,
                rec.fee_paid,
                rec.slippage_pct,
                rec.slippage_usdt,
                rec.latency_ms,
                rec.quality_score,
                rec.outcome,
                rec.retry_count,
                rec.idempotency_key,
            )
        return _was_inserted(result)

    # ------------------------------------------------------------------
    # F. Accounting records
    # ------------------------------------------------------------------

    async def insert_accounting_record(self, rec: AccountingEvidenceRecord) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO evidence_accounting_records (
                    record_id, session_id, captured_at, order_id, symbol, side,
                    quantity, price, fee_usdt, realized_pnl, cost_basis,
                    lot_id, idempotency_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                rec.record_id,
                rec.session_id,
                rec.captured_at,
                rec.order_id,
                rec.symbol,
                rec.side,
                rec.quantity,
                rec.price,
                rec.fee_usdt,
                rec.realized_pnl,
                rec.cost_basis,
                rec.lot_id,
                rec.idempotency_key,
            )
        return _was_inserted(result)

    # ------------------------------------------------------------------
    # G. Reconciliation reports
    # ------------------------------------------------------------------

    async def insert_reconciliation_report(self, rpt: ReconciliationEvidenceReport) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO evidence_reconciliation_reports (
                    report_id, session_id, run_at, severity,
                    order_discrepancies, balance_discrepancies, position_discrepancies,
                    orders_blocked, mismatch_count, idempotency_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                rpt.report_id,
                rpt.session_id,
                rpt.run_at,
                rpt.severity.value,
                json.dumps(rpt.order_discrepancies),
                json.dumps(rpt.balance_discrepancies),
                json.dumps(rpt.position_discrepancies),
                rpt.orders_blocked,
                rpt.mismatch_count,
                rpt.idempotency_key,
            )
        return _was_inserted(result)

    # ------------------------------------------------------------------
    # H. Alert incidents
    # ------------------------------------------------------------------

    async def insert_alert_incident(self, inc: AlertIncidentEvidence) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO evidence_alert_incidents (
                    incident_id, session_id, fired_at, cleared_at, severity,
                    source, title, detail, acknowledged, acknowledged_by,
                    runbook_url, idempotency_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                inc.incident_id,
                inc.session_id,
                inc.fired_at,
                inc.cleared_at,
                inc.severity.value,
                inc.source,
                inc.title,
                inc.detail,
                inc.acknowledged,
                inc.acknowledged_by,
                inc.runbook_url,
                inc.idempotency_key,
            )
        return _was_inserted(result)

    # ------------------------------------------------------------------
    # I. Daily summaries
    # ------------------------------------------------------------------

    async def insert_daily_summary(self, summary: DailyEvidenceSummary) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO evidence_daily_summaries (
                    summary_id, session_id, summary_date,
                    starting_equity, ending_equity, pnl, pnl_pct,
                    max_drawdown_pct, trade_count, rejected_order_count,
                    partial_fill_count, signal_count, reconciliation_critical_count,
                    alert_count, incident_count, notes, generated_at, idempotency_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                summary.summary_id,
                summary.session_id,
                summary.summary_date,
                summary.starting_equity,
                summary.ending_equity,
                summary.pnl,
                summary.pnl_pct,
                summary.max_drawdown_pct,
                summary.trade_count,
                summary.rejected_order_count,
                summary.partial_fill_count,
                summary.signal_count,
                summary.reconciliation_critical_count,
                summary.alert_count,
                summary.incident_count,
                summary.notes,
                summary.generated_at,
                summary.idempotency_key,
            )
        inserted = _was_inserted(result)
        if inserted:
            log.info(
                "evidence_daily_summary_inserted",
                session_id=str(summary.session_id),
                date=summary.summary_date.isoformat(),
            )
        return inserted

    # ------------------------------------------------------------------
    # J. Weekly summaries
    # ------------------------------------------------------------------

    async def insert_weekly_summary(self, summary: WeeklyEvidenceSummary) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO evidence_weekly_summaries (
                    summary_id, session_id, week_start, week_end,
                    starting_equity, ending_equity, pnl, pnl_pct,
                    max_drawdown_pct, trade_count, rejected_order_count,
                    partial_fill_count, parity_score, strategy_metrics,
                    incidents, generated_at, idempotency_key
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
                ON CONFLICT (idempotency_key) DO NOTHING
                """,
                summary.summary_id,
                summary.session_id,
                summary.week_start,
                summary.week_end,
                summary.starting_equity,
                summary.ending_equity,
                summary.pnl,
                summary.pnl_pct,
                summary.max_drawdown_pct,
                summary.trade_count,
                summary.rejected_order_count,
                summary.partial_fill_count,
                summary.parity_score,
                json.dumps(summary.strategy_metrics, default=str),
                json.dumps(summary.incidents, default=str),
                summary.generated_at,
                summary.idempotency_key,
            )
        inserted = _was_inserted(result)
        if inserted:
            log.info(
                "evidence_weekly_summary_inserted",
                session_id=str(summary.session_id),
                week_start=summary.week_start.isoformat(),
            )
        return inserted

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    async def list_daily_summaries(
        self,
        session_id: uuid.UUID,
        limit: int = 90,
    ) -> list[dict[str, Any]]:
        """Return daily summaries for a session, newest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT summary_id, session_id, summary_date,
                       starting_equity, ending_equity, pnl, pnl_pct,
                       max_drawdown_pct, trade_count, rejected_order_count,
                       partial_fill_count, signal_count,
                       reconciliation_critical_count, alert_count,
                       incident_count, notes, generated_at
                FROM evidence_daily_summaries
                WHERE session_id = $1
                ORDER BY summary_date DESC
                LIMIT $2
                """,
                session_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def list_weekly_summaries(
        self,
        session_id: uuid.UUID,
        limit: int = 26,
    ) -> list[dict[str, Any]]:
        """Return weekly summaries for a session, newest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT summary_id, session_id, week_start, week_end,
                       starting_equity, ending_equity, pnl, pnl_pct,
                       max_drawdown_pct, trade_count, rejected_order_count,
                       partial_fill_count, parity_score, strategy_metrics,
                       incidents, generated_at
                FROM evidence_weekly_summaries
                WHERE session_id = $1
                ORDER BY week_start DESC
                LIMIT $2
                """,
                session_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def list_portfolio_snapshots(
        self,
        session_id: uuid.UUID,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT snapshot_id, captured_at, cash_balance, total_equity,
                       daily_pnl, daily_drawdown_pct, positions, source
                FROM evidence_portfolio_snapshots
                WHERE session_id = $1
                ORDER BY captured_at DESC
                LIMIT $2
                """,
                session_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def list_signal_snapshots(
        self,
        session_id: uuid.UUID,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT snapshot_id, captured_at, symbol, strategy_id, signal,
                       strength, indicators, bars_used, market_context
                FROM evidence_signal_snapshots
                WHERE session_id = $1
                ORDER BY captured_at DESC
                LIMIT $2
                """,
                session_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def list_reconciliation_reports(
        self,
        session_id: uuid.UUID,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT report_id, run_at, severity, mismatch_count, orders_blocked,
                       order_discrepancies, balance_discrepancies, position_discrepancies
                FROM evidence_reconciliation_reports
                WHERE session_id = $1
                ORDER BY run_at DESC
                LIMIT $2
                """,
                session_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def get_session_report(self, session_id: uuid.UUID) -> dict[str, Any]:
        """Return a summary dict combining all evidence for a session."""
        async with self._pool.acquire() as conn:
            session_row = await conn.fetchrow(
                """
                SELECT session_id, started_at, ended_at, environment, git_commit,
                       config_snapshot_hash, paper_capital, symbols, strategies,
                       status, notes
                FROM evidence_sessions
                WHERE session_id = $1
                """,
                session_id,
            )
            if session_row is None:
                return {}

            trade_count = await conn.fetchval(
                "SELECT COUNT(*) FROM evidence_tca_records WHERE session_id = $1",
                session_id,
            )
            portfolio_count = await conn.fetchval(
                "SELECT COUNT(*) FROM evidence_portfolio_snapshots WHERE session_id = $1",
                session_id,
            )
            signal_count = await conn.fetchval(
                "SELECT COUNT(*) FROM evidence_signal_snapshots WHERE session_id = $1",
                session_id,
            )
            recon_critical = await conn.fetchval(
                """
                SELECT COUNT(*) FROM evidence_reconciliation_reports
                WHERE session_id = $1 AND severity = 'critical'
                """,
                session_id,
            )
            incident_count = await conn.fetchval(
                "SELECT COUNT(*) FROM evidence_alert_incidents WHERE session_id = $1",
                session_id,
            )
            daily_count = await conn.fetchval(
                "SELECT COUNT(*) FROM evidence_daily_summaries WHERE session_id = $1",
                session_id,
            )

        return {
            "session": dict(session_row),
            "trade_count": trade_count,
            "portfolio_snapshot_count": portfolio_count,
            "signal_snapshot_count": signal_count,
            "reconciliation_critical_count": recon_critical,
            "incident_count": incident_count,
            "daily_summary_count": daily_count,
        }

    async def export_session_json(self, session_id: uuid.UUID) -> dict[str, Any]:
        """Export all evidence for a session as a JSON-serialisable dict."""
        report = await self.get_session_report(session_id)
        if not report:
            return {}

        daily = await self.list_daily_summaries(session_id, limit=365)
        weekly = await self.list_weekly_summaries(session_id, limit=52)
        portfolio = await self.list_portfolio_snapshots(session_id, limit=500)
        recon = await self.list_reconciliation_reports(session_id, limit=500)

        return {
            "exported_at": _now().isoformat(),
            "session_id": str(session_id),
            "report": report,
            "daily_summaries": [_serialise_row(r) for r in daily],
            "weekly_summaries": [_serialise_row(r) for r in weekly],
            "portfolio_snapshots": [_serialise_row(r) for r in portfolio],
            "reconciliation_reports": [_serialise_row(r) for r in recon],
        }

    async def export_session_csv(self, session_id: uuid.UUID) -> str:
        """Export daily summaries for a session as CSV text."""
        rows = await self.list_daily_summaries(session_id, limit=365)
        if not rows:
            return "date,pnl,pnl_pct,trade_count,max_drawdown_pct\n"
        headers = [
            "date",
            "pnl",
            "pnl_pct",
            "trade_count",
            "rejected_order_count",
            "partial_fill_count",
            "max_drawdown_pct",
            "reconciliation_critical_count",
            "alert_count",
        ]
        lines = [",".join(headers)]
        for r in rows:
            lines.append(
                ",".join(
                    [
                        str(r.get("summary_date", "")),
                        str(r.get("pnl", "")),
                        str(r.get("pnl_pct", "")),
                        str(r.get("trade_count", "")),
                        str(r.get("rejected_order_count", "")),
                        str(r.get("partial_fill_count", "")),
                        str(r.get("max_drawdown_pct", "")),
                        str(r.get("reconciliation_critical_count", "")),
                        str(r.get("alert_count", "")),
                    ]
                )
            )
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_session(row: asyncpg.Record) -> PaperSession:
        import json as _json

        return PaperSession(
            session_id=row["session_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            environment=row["environment"],
            git_commit=row["git_commit"],
            config_snapshot_hash=row["config_snapshot_hash"],
            paper_capital=Decimal(str(row["paper_capital"])),
            symbols=_json.loads(row["symbols"])
            if isinstance(row["symbols"], str)
            else (row["symbols"] or []),
            strategies=_json.loads(row["strategies"])
            if isinstance(row["strategies"], str)
            else (row["strategies"] or []),
            status=SessionStatus(row["status"]),
            notes=row["notes"] or "",
        )

    async def build_daily_summary(
        self,
        session_id: uuid.UUID,
        summary_date: date,
    ) -> DailyEvidenceSummary | None:
        """Compute a DailyEvidenceSummary from evidence tables for the given date.

        Returns None if no portfolio snapshots exist for that date.
        """
        date_start = datetime(
            summary_date.year, summary_date.month, summary_date.day, 0, 0, 0, tzinfo=UTC
        )
        date_end = datetime(
            summary_date.year, summary_date.month, summary_date.day, 23, 59, 59, tzinfo=UTC
        )

        async with self._pool.acquire() as conn:
            # Starting and ending equity from portfolio snapshots
            first_snap = await conn.fetchrow(
                """
                SELECT total_equity FROM evidence_portfolio_snapshots
                WHERE session_id = $1 AND captured_at >= $2 AND captured_at <= $3
                ORDER BY captured_at ASC LIMIT 1
                """,
                session_id,
                date_start,
                date_end,
            )
            last_snap = await conn.fetchrow(
                """
                SELECT total_equity, daily_drawdown_pct FROM evidence_portfolio_snapshots
                WHERE session_id = $1 AND captured_at >= $2 AND captured_at <= $3
                ORDER BY captured_at DESC LIMIT 1
                """,
                session_id,
                date_start,
                date_end,
            )
            if first_snap is None or last_snap is None:
                return None

            starting_equity = Decimal(str(first_snap["total_equity"]))
            ending_equity = Decimal(str(last_snap["total_equity"]))
            max_dd = Decimal(str(last_snap["daily_drawdown_pct"]))

            trade_count = (
                await conn.fetchval(
                    """
                SELECT COUNT(*) FROM evidence_tca_records
                WHERE session_id = $1 AND captured_at >= $2 AND captured_at <= $3
                  AND outcome = 'filled'
                """,
                    session_id,
                    date_start,
                    date_end,
                )
                or 0
            )

            rejected_count = (
                await conn.fetchval(
                    """
                SELECT COUNT(*) FROM evidence_tca_records
                WHERE session_id = $1 AND captured_at >= $2 AND captured_at <= $3
                  AND outcome = 'rejected'
                """,
                    session_id,
                    date_start,
                    date_end,
                )
                or 0
            )

            partial_count = (
                await conn.fetchval(
                    """
                SELECT COUNT(*) FROM evidence_tca_records
                WHERE session_id = $1 AND captured_at >= $2 AND captured_at <= $3
                  AND outcome = 'partial'
                """,
                    session_id,
                    date_start,
                    date_end,
                )
                or 0
            )

            signal_count = (
                await conn.fetchval(
                    """
                SELECT COUNT(*) FROM evidence_signal_snapshots
                WHERE session_id = $1 AND captured_at >= $2 AND captured_at <= $3
                """,
                    session_id,
                    date_start,
                    date_end,
                )
                or 0
            )

            recon_critical = (
                await conn.fetchval(
                    """
                SELECT COUNT(*) FROM evidence_reconciliation_reports
                WHERE session_id = $1 AND run_at >= $2 AND run_at <= $3
                  AND severity = 'critical'
                """,
                    session_id,
                    date_start,
                    date_end,
                )
                or 0
            )

            alert_count = (
                await conn.fetchval(
                    """
                SELECT COUNT(*) FROM evidence_alert_incidents
                WHERE session_id = $1 AND fired_at >= $2 AND fired_at <= $3
                """,
                    session_id,
                    date_start,
                    date_end,
                )
                or 0
            )

        pnl = ending_equity - starting_equity
        pnl_pct = (pnl / starting_equity * 100) if starting_equity != 0 else Decimal("0")

        idem_key = f"daily_summary:{session_id}:{summary_date.isoformat()}"
        return DailyEvidenceSummary(
            session_id=session_id,
            summary_date=summary_date,
            starting_equity=starting_equity,
            ending_equity=ending_equity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            max_drawdown_pct=max_dd,
            trade_count=int(trade_count),
            rejected_order_count=int(rejected_count),
            partial_fill_count=int(partial_count),
            signal_count=int(signal_count),
            reconciliation_critical_count=int(recon_critical),
            alert_count=int(alert_count),
            incident_count=int(alert_count),
            generated_at=_now(),
            idempotency_key=idem_key,
        )


def _serialise_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert asyncpg row values to JSON-safe types."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        elif isinstance(v, date):
            out[k] = v.isoformat()
        elif isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: EvidenceStore | None = None
_current_session_id: uuid.UUID | None = None


def init_evidence_store(pool: asyncpg.Pool) -> EvidenceStore:
    """Initialise the module-level EvidenceStore. Call once at startup."""
    global _store
    _store = EvidenceStore(pool)
    log.info("evidence_store_initialised")
    return _store


def get_evidence_store() -> EvidenceStore:
    """Return the module-level EvidenceStore. Raises if not initialised."""
    if _store is None:
        raise RuntimeError("EvidenceStore not initialised. Call init_evidence_store() at startup.")
    return _store


def set_current_session_id(sid: uuid.UUID) -> None:
    global _current_session_id
    _current_session_id = sid


def get_current_session_id() -> uuid.UUID | None:
    return _current_session_id
