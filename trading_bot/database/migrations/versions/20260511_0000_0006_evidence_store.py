"""Add paper testing evidence store tables.

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-11 00:00:00 UTC

Tables created:
  evidence_sessions              — paper testing session lifecycle
  evidence_portfolio_snapshots   — portfolio equity snapshots (15-min cadence)
  evidence_signal_snapshots      — signal output snapshots
  evidence_backtest_snapshots    — per-strategy backtest result snapshots
  evidence_tca_records           — transaction cost analysis per fill
  evidence_accounting_records    — per-fill accounting ledger entries
  evidence_reconciliation_reports — OMS reconciliation run results
  evidence_alert_incidents       — alert/incident timeline
  evidence_daily_summaries       — daily roll-up (generated at UTC midnight)
  evidence_weekly_summaries      — weekly roll-up (generated at week boundary)

Online migration notes:
  - All CREATE TABLE IF NOT EXISTS (safe to re-run)
  - UNIQUE constraint on idempotency_key enables ON CONFLICT DO NOTHING inserts
  - All timestamps are TIMESTAMPTZ (UTC)
  - JSONB columns store lists/dicts; validated by application layer
"""

from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── evidence_sessions ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_sessions (
            session_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            started_at              TIMESTAMPTZ NOT NULL,
            ended_at                TIMESTAMPTZ,
            environment             TEXT NOT NULL DEFAULT 'development',
            git_commit              TEXT,
            config_snapshot_hash    TEXT NOT NULL DEFAULT '',
            paper_capital           NUMERIC(20, 8) NOT NULL DEFAULT 10000,
            symbols                 JSONB NOT NULL DEFAULT '[]',
            strategies              JSONB NOT NULL DEFAULT '[]',
            status                  TEXT NOT NULL DEFAULT 'running',
            notes                   TEXT NOT NULL DEFAULT ''
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_sessions_status_started
        ON evidence_sessions (status, started_at DESC)
    """)

    # ── evidence_portfolio_snapshots ──────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_portfolio_snapshots (
            snapshot_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id          UUID NOT NULL REFERENCES evidence_sessions(session_id),
            captured_at         TIMESTAMPTZ NOT NULL,
            cash_balance        NUMERIC(20, 8) NOT NULL,
            total_equity        NUMERIC(20, 8) NOT NULL,
            daily_pnl           NUMERIC(20, 8) NOT NULL DEFAULT 0,
            daily_drawdown_pct  NUMERIC(10, 6) NOT NULL DEFAULT 0,
            positions           JSONB NOT NULL DEFAULT '{}',
            source              TEXT NOT NULL DEFAULT 'scheduler',
            idempotency_key     TEXT NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_portfolio_snapshots_session_captured
        ON evidence_portfolio_snapshots (session_id, captured_at DESC)
    """)

    # ── evidence_signal_snapshots ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_signal_snapshots (
            snapshot_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id          UUID NOT NULL REFERENCES evidence_sessions(session_id),
            captured_at         TIMESTAMPTZ NOT NULL,
            symbol              TEXT NOT NULL,
            strategy_id         TEXT NOT NULL DEFAULT '',
            signal              TEXT NOT NULL,
            strength            NUMERIC(10, 6),
            indicators          JSONB NOT NULL DEFAULT '{}',
            bars_used           INTEGER,
            market_context      JSONB,
            idempotency_key     TEXT NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_signal_snapshots_session_captured
        ON evidence_signal_snapshots (session_id, captured_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_signal_snapshots_symbol_strategy
        ON evidence_signal_snapshots (symbol, strategy_id, captured_at DESC)
    """)

    # ── evidence_backtest_snapshots ───────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_backtest_snapshots (
            snapshot_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id              UUID NOT NULL REFERENCES evidence_sessions(session_id),
            captured_at             TIMESTAMPTZ NOT NULL,
            strategy_id             TEXT NOT NULL,
            symbol                  TEXT NOT NULL,
            dataset_snapshot_ids    JSONB NOT NULL DEFAULT '[]',
            period_start            TIMESTAMPTZ NOT NULL,
            period_end              TIMESTAMPTZ NOT NULL,
            metrics                 JSONB NOT NULL DEFAULT '{}',
            config                  JSONB NOT NULL DEFAULT '{}',
            gross_return_pct        NUMERIC(10, 6),
            net_return_pct          NUMERIC(10, 6),
            max_drawdown_pct        NUMERIC(10, 6),
            sharpe                  NUMERIC(10, 6),
            total_trades            INTEGER,
            idempotency_key         TEXT NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_backtest_snapshots_session_strategy
        ON evidence_backtest_snapshots (session_id, strategy_id, captured_at DESC)
    """)

    # ── evidence_tca_records ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_tca_records (
            record_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id          UUID NOT NULL REFERENCES evidence_sessions(session_id),
            captured_at         TIMESTAMPTZ NOT NULL,
            order_id            TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            strategy_id         TEXT NOT NULL DEFAULT '',
            side                TEXT NOT NULL,
            signal_price        NUMERIC(20, 8) NOT NULL,
            fill_price          NUMERIC(20, 8) NOT NULL,
            quantity            NUMERIC(20, 8) NOT NULL,
            fee_paid            NUMERIC(20, 8) NOT NULL DEFAULT 0,
            slippage_pct        NUMERIC(10, 8) NOT NULL DEFAULT 0,
            slippage_usdt       NUMERIC(20, 8) NOT NULL DEFAULT 0,
            latency_ms          NUMERIC(10, 3) NOT NULL DEFAULT 0,
            quality_score       TEXT NOT NULL DEFAULT 'excellent',
            outcome             TEXT NOT NULL,
            retry_count         INTEGER NOT NULL DEFAULT 0,
            idempotency_key     TEXT NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_tca_records_session_captured
        ON evidence_tca_records (session_id, captured_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_tca_records_order_id
        ON evidence_tca_records (order_id)
    """)

    # ── evidence_accounting_records ───────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_accounting_records (
            record_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id          UUID NOT NULL REFERENCES evidence_sessions(session_id),
            captured_at         TIMESTAMPTZ NOT NULL,
            order_id            TEXT NOT NULL,
            symbol              TEXT NOT NULL,
            side                TEXT NOT NULL,
            quantity            NUMERIC(20, 8) NOT NULL,
            price               NUMERIC(20, 8) NOT NULL,
            fee_usdt            NUMERIC(20, 8) NOT NULL DEFAULT 0,
            realized_pnl        NUMERIC(20, 8),
            cost_basis          NUMERIC(20, 8),
            lot_id              TEXT,
            idempotency_key     TEXT NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_accounting_records_session_captured
        ON evidence_accounting_records (session_id, captured_at DESC)
    """)

    # ── evidence_reconciliation_reports ──────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_reconciliation_reports (
            report_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id              UUID NOT NULL REFERENCES evidence_sessions(session_id),
            run_at                  TIMESTAMPTZ NOT NULL,
            severity                TEXT NOT NULL DEFAULT 'ok',
            order_discrepancies     JSONB NOT NULL DEFAULT '[]',
            balance_discrepancies   JSONB NOT NULL DEFAULT '[]',
            position_discrepancies  JSONB NOT NULL DEFAULT '[]',
            orders_blocked          BOOLEAN NOT NULL DEFAULT FALSE,
            mismatch_count          INTEGER NOT NULL DEFAULT 0,
            idempotency_key         TEXT NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_reconciliation_reports_session_run_at
        ON evidence_reconciliation_reports (session_id, run_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_reconciliation_severity
        ON evidence_reconciliation_reports (session_id, severity, run_at DESC)
    """)

    # ── evidence_alert_incidents ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_alert_incidents (
            incident_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id          UUID NOT NULL REFERENCES evidence_sessions(session_id),
            fired_at            TIMESTAMPTZ NOT NULL,
            cleared_at          TIMESTAMPTZ,
            severity            TEXT NOT NULL DEFAULT 'info',
            source              TEXT NOT NULL DEFAULT '',
            title               TEXT NOT NULL,
            detail              TEXT NOT NULL DEFAULT '',
            acknowledged        BOOLEAN NOT NULL DEFAULT FALSE,
            acknowledged_by     TEXT,
            runbook_url         TEXT,
            idempotency_key     TEXT NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_alert_incidents_session_fired
        ON evidence_alert_incidents (session_id, fired_at DESC)
    """)

    # ── evidence_daily_summaries ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_daily_summaries (
            summary_id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id                      UUID NOT NULL REFERENCES evidence_sessions(session_id),
            summary_date                    DATE NOT NULL,
            starting_equity                 NUMERIC(20, 8) NOT NULL,
            ending_equity                   NUMERIC(20, 8) NOT NULL,
            pnl                             NUMERIC(20, 8) NOT NULL,
            pnl_pct                         NUMERIC(10, 6) NOT NULL,
            max_drawdown_pct                NUMERIC(10, 6) NOT NULL DEFAULT 0,
            trade_count                     INTEGER NOT NULL DEFAULT 0,
            rejected_order_count            INTEGER NOT NULL DEFAULT 0,
            partial_fill_count              INTEGER NOT NULL DEFAULT 0,
            signal_count                    INTEGER NOT NULL DEFAULT 0,
            reconciliation_critical_count   INTEGER NOT NULL DEFAULT 0,
            alert_count                     INTEGER NOT NULL DEFAULT 0,
            incident_count                  INTEGER NOT NULL DEFAULT 0,
            notes                           TEXT NOT NULL DEFAULT '',
            generated_at                    TIMESTAMPTZ NOT NULL,
            idempotency_key                 TEXT NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_daily_summaries_session_date
        ON evidence_daily_summaries (session_id, summary_date DESC)
    """)

    # ── evidence_weekly_summaries ─────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS evidence_weekly_summaries (
            summary_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id              UUID NOT NULL REFERENCES evidence_sessions(session_id),
            week_start              DATE NOT NULL,
            week_end                DATE NOT NULL,
            starting_equity         NUMERIC(20, 8) NOT NULL,
            ending_equity           NUMERIC(20, 8) NOT NULL,
            pnl                     NUMERIC(20, 8) NOT NULL,
            pnl_pct                 NUMERIC(10, 6) NOT NULL,
            max_drawdown_pct        NUMERIC(10, 6) NOT NULL DEFAULT 0,
            trade_count             INTEGER NOT NULL DEFAULT 0,
            rejected_order_count    INTEGER NOT NULL DEFAULT 0,
            partial_fill_count      INTEGER NOT NULL DEFAULT 0,
            parity_score            NUMERIC(10, 6),
            strategy_metrics        JSONB NOT NULL DEFAULT '{}',
            incidents               JSONB NOT NULL DEFAULT '[]',
            generated_at            TIMESTAMPTZ NOT NULL,
            idempotency_key         TEXT NOT NULL UNIQUE
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_evidence_weekly_summaries_session_week
        ON evidence_weekly_summaries (session_id, week_start DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS evidence_weekly_summaries")
    op.execute("DROP TABLE IF EXISTS evidence_daily_summaries")
    op.execute("DROP TABLE IF EXISTS evidence_alert_incidents")
    op.execute("DROP TABLE IF EXISTS evidence_reconciliation_reports")
    op.execute("DROP TABLE IF EXISTS evidence_accounting_records")
    op.execute("DROP TABLE IF EXISTS evidence_tca_records")
    op.execute("DROP TABLE IF EXISTS evidence_backtest_snapshots")
    op.execute("DROP TABLE IF EXISTS evidence_signal_snapshots")
    op.execute("DROP TABLE IF EXISTS evidence_portfolio_snapshots")
    op.execute("DROP TABLE IF EXISTS evidence_sessions")
