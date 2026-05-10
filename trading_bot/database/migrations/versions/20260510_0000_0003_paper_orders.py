"""Add paper_orders table — persistent OMS order history.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-10 00:00:00 UTC

Table created:
- paper_orders: durable record of all paper-traded orders (filled + rejected)
  Survives app restarts. Used by OrderTracker.load_recent() on startup.
  Also feeds the promotion pipeline metrics collector.

Online migration notes:
- CREATE TABLE IF NOT EXISTS (safe to re-run)
- No partitioning — order volume is low (< 1000/day)
"""

from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_orders (
            order_id        TEXT PRIMARY KEY,
            strategy_id     TEXT NOT NULL DEFAULT '',
            symbol          TEXT NOT NULL,
            exchange        TEXT NOT NULL DEFAULT 'binance',
            side            TEXT NOT NULL,
            order_type      TEXT NOT NULL DEFAULT 'market',
            requested_qty   NUMERIC(20, 8) NOT NULL,
            filled_qty      NUMERIC(20, 8),
            fill_price      NUMERIC(20, 8),
            status          TEXT NOT NULL,
            reject_reason   TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_paper_orders_strategy_created
        ON paper_orders (strategy_id, created_at DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_paper_orders_symbol_created
        ON paper_orders (symbol, created_at DESC)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS paper_orders")
