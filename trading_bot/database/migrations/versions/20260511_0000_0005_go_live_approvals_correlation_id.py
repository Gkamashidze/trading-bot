"""Add correlation_id to go_live_approvals and persist governance registries.

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-11 00:00:00 UTC

Changes:
  - go_live_approvals: add correlation_id column (idempotency key for approval ops)
  - experiments: new table for ExperimentRegistry persistent storage
  - strategy_registry: new table for StrategyRegistry persistent storage
"""

from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── go_live_approvals: add correlation_id ─────────────────────────────────
    op.execute("""
        ALTER TABLE go_live_approvals
        ADD COLUMN IF NOT EXISTS correlation_id TEXT NOT NULL DEFAULT ''
    """)

    # ── experiments registry ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS experiments (
            experiment_id       UUID PRIMARY KEY,
            strategy_id         TEXT NOT NULL,
            dataset_snapshot_ids JSONB NOT NULL DEFAULT '[]',
            params_hash         TEXT NOT NULL DEFAULT '',
            code_hash           TEXT NOT NULL DEFAULT '',
            seed                INTEGER NOT NULL DEFAULT 0,
            metrics             JSONB NOT NULL DEFAULT '{}',
            status              TEXT NOT NULL DEFAULT 'draft',
            approved_by         TEXT NOT NULL DEFAULT '',
            approved_at         TIMESTAMPTZ,
            notes               TEXT NOT NULL DEFAULT '',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_experiments_strategy_id
        ON experiments (strategy_id, created_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_experiments_status
        ON experiments (status, created_at DESC)
    """)

    # ── strategy registry ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS strategy_registry (
            strategy_id             TEXT NOT NULL,
            version                 TEXT NOT NULL,
            owner                   TEXT NOT NULL DEFAULT 'unassigned',
            params_hash             TEXT NOT NULL DEFAULT '',
            code_hash               TEXT NOT NULL DEFAULT '',
            research_dataset_hash   TEXT NOT NULL DEFAULT '',
            backtest_result_id      TEXT NOT NULL DEFAULT '',
            promotion_status        TEXT NOT NULL DEFAULT 'pending',
            registered_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expiry_date             TIMESTAMPTZ,
            review_date             TIMESTAMPTZ,
            approval_history        JSONB NOT NULL DEFAULT '[]',
            dataset_snapshot_ids    JSONB NOT NULL DEFAULT '[]',
            PRIMARY KEY (strategy_id, version)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_strategy_registry_status
        ON strategy_registry (promotion_status, registered_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategy_registry")
    op.execute("DROP TABLE IF EXISTS experiments")
    op.execute("""
        ALTER TABLE go_live_approvals
        DROP COLUMN IF EXISTS correlation_id
    """)
