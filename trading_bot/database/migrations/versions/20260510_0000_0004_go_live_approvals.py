"""Add go_live_approvals table for go-live readiness gate.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-10 00:00:00 UTC

Tables created:
  go_live_approvals — operator approval records for go-live gate decisions

Notes:
  - Append-only; no UPDATE/DELETE on this table (operator decisions are immutable)
  - checklist_snapshot JSONB preserves the full criteria state at approval time
  - All timestamps are TIMESTAMPTZ (UTC)
"""

from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS go_live_approvals (
            approval_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            operator                TEXT NOT NULL,
            approved                BOOLEAN NOT NULL DEFAULT FALSE,
            comment                 TEXT NOT NULL DEFAULT '',
            approved_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            rollback_plan_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
            risk_sign_off_by        TEXT NOT NULL DEFAULT '',
            checklist_snapshot      JSONB NOT NULL DEFAULT '{}'
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_go_live_approvals_approved_at
        ON go_live_approvals (approved_at DESC)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_go_live_approvals_operator
        ON go_live_approvals (operator, approved_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS go_live_approvals")
