"""Update feature flag reason text — stages 2-7 are now implemented.

Revision ID: 0002
Revises: 0001
Create Date: 2025-05-10 00:00:00 UTC

Rationale: the initial seed (0001) set placeholder reason text for flags
that were not yet implemented at Stage 0. Stages 2-7 are complete, so
update the reason column to reflect current state.

Enabled state is NOT changed — that is an operational decision made via
the dashboard or /kill Telegram command.
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE feature_flags
        SET reason = 'Real-time WebSocket market data streams (Stage 2 — implemented)'
        WHERE flag_name = 'websocket_enabled'
          AND reason = 'Stage 2 — not yet implemented'
    """)

    op.execute("""
        UPDATE feature_flags
        SET reason = 'SMA crossover strategy signal generation (Stage 3 — implemented)'
        WHERE flag_name = 'strategy_sma_enabled'
          AND reason = 'Stage 3 — not yet implemented'
    """)

    op.execute("""
        UPDATE feature_flags
        SET reason = 'RSI mean-reversion strategy signal generation (Stage 3 — implemented)'
        WHERE flag_name = 'strategy_rsi_enabled'
          AND reason = 'Stage 3 — not yet implemented'
    """)

    op.execute("""
        UPDATE feature_flags
        SET reason = 'Synthetic canary trades at market open (Stage 5 — not yet activated)'
        WHERE flag_name = 'canary_trade_enabled'
          AND reason = 'Stage 5 — not yet implemented'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE feature_flags
        SET reason = 'Stage 2 — not yet implemented'
        WHERE flag_name = 'websocket_enabled'
    """)

    op.execute("""
        UPDATE feature_flags
        SET reason = 'Stage 3 — not yet implemented'
        WHERE flag_name IN ('strategy_sma_enabled', 'strategy_rsi_enabled')
    """)

    op.execute("""
        UPDATE feature_flags
        SET reason = 'Stage 5 — not yet implemented'
        WHERE flag_name = 'canary_trade_enabled'
    """)
