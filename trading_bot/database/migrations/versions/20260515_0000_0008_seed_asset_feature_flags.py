"""Seed asset-universe feature flags.

Revision ID: 20260515_0000_0008
Revises: 20260513_0000_0007
Create Date: 2026-05-15

Existing databases predate the asset universe expansion. This migration inserts
missing asset-group flags without overriding operator-managed values.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO feature_flags (flag_name, enabled, changed_by, reason)
        VALUES
            ('asset_group_crypto_phase1_enabled', TRUE,  'system', 'Phase 1 crypto: BTC/USDT + ETH/USDT'),
            ('asset_group_crypto_phase2_enabled', FALSE, 'system', 'Phase 2 crypto: SOL/USDT'),
            ('asset_group_crypto_phase3_enabled', FALSE, 'system', 'Phase 3 crypto: BNB/USDT + XRP/USDT'),
            ('asset_group_crypto_phase4_enabled', FALSE, 'system', 'Phase 4 crypto: LINK/USDT'),
            ('asset_group_etf_wave1_enabled',     TRUE,  'system', 'Wave 1 ETF: SPY/QQQ/SOXX/IBIT via Alpaca'),
            ('asset_group_etf_phase5_enabled',    FALSE, 'system', 'Future ETF wave: IWM/TLT/GLD via Alpaca'),
            ('asset_experimental_doge_enabled',   FALSE, 'system', 'Experimental DOGE/USDT')
        ON CONFLICT (flag_name) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM feature_flags
        WHERE flag_name IN (
            'asset_group_crypto_phase1_enabled',
            'asset_group_crypto_phase2_enabled',
            'asset_group_crypto_phase3_enabled',
            'asset_group_crypto_phase4_enabled',
            'asset_group_etf_wave1_enabled',
            'asset_group_etf_phase5_enabled',
            'asset_experimental_doge_enabled'
        )
        AND changed_by = 'system'
        """
    )
