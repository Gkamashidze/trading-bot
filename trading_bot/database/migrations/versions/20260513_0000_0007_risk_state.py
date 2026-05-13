"""Add risk_state table — single-row persistent risk state store.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-13 00:00:00 UTC

Table: risk_state
  Single row (id=1) — upsert on every mutation.
  Replaces InMemoryRiskStateStore; survives process restarts.
  Seeded at startup by PostgresRiskStateStore._ensure_row().
"""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk_state (
            id                              INTEGER PRIMARY KEY CHECK (id = 1),
            kill_switch_active              BOOLEAN     NOT NULL DEFAULT FALSE,
            kill_switch_reason              TEXT        NOT NULL DEFAULT '',
            kill_switch_activated_by        TEXT        NOT NULL DEFAULT '',
            kill_switch_activated_at        TIMESTAMPTZ,
            reconciler_block_active         BOOLEAN     NOT NULL DEFAULT FALSE,
            reconciler_block_reason         TEXT        NOT NULL DEFAULT '',
            emergency_halt_active           BOOLEAN     NOT NULL DEFAULT FALSE,
            emergency_halt_reason           TEXT,
            emergency_halt_at               TIMESTAMPTZ,
            emergency_halt_by               TEXT        NOT NULL DEFAULT '',
            strategy_states                 JSONB       NOT NULL DEFAULT '{}',
            daily_loss_usd                  NUMERIC(20, 8) NOT NULL DEFAULT 0,
            weekly_loss_usd                 NUMERIC(20, 8) NOT NULL DEFAULT 0,
            capital_allocation_overrides    JSONB       NOT NULL DEFAULT '{}',
            operator_locks                  JSONB       NOT NULL DEFAULT '{}',
            last_updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_updated_by                 TEXT        NOT NULL DEFAULT 'system',
            version                         INTEGER     NOT NULL DEFAULT 0
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS risk_state")
