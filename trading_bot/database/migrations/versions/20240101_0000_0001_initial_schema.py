"""Initial schema: audit_log, feature_flags, idempotency_keys, ohlcv_metadata

Revision ID: 0001
Revises: None
Create Date: 2024-01-01 00:00:00 UTC

Tables created:
- audit_log: append-only, hash-chained event log (WORM)
- feature_flags: runtime feature flag store
- idempotency_keys: deduplication store with TTL
- ohlcv_metadata: lineage tracking for Parquet data files

OLAP data (OHLCV bars) is stored in Parquet files, NOT in Postgres.
Postgres stores only metadata/lineage. DuckDB queries the Parquet files.

Online migration notes:
- All CREATE TABLE use IF NOT EXISTS (safe to re-run)
- Index creation uses CONCURRENTLY (no table lock)
- Partitioning: audit_log uses monthly partitions (set up via pg_partman in Stage 7)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── audit_log ─────────────────────────────────────────────────────────
    # Append-only, hash-chained. No UPDATE or DELETE should ever run on this table.
    # WORM enforcement: revoke UPDATE/DELETE from the app DB user after creation.
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_type      TEXT NOT NULL,
            schema_version  TEXT NOT NULL DEFAULT '1.0',
            occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            correlation_id  TEXT NOT NULL DEFAULT '',
            actor           TEXT NOT NULL DEFAULT 'system',
            payload         JSONB NOT NULL DEFAULT '{}',
            prev_event_hash TEXT,
            event_hash      TEXT NOT NULL,
            config_snapshot JSONB NOT NULL DEFAULT '{}'
        )
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_log_occurred_at
        ON audit_log (occurred_at DESC)
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_log_correlation_id
        ON audit_log (correlation_id)
        WHERE correlation_id != ''
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_log_event_type
        ON audit_log (event_type, occurred_at DESC)
    """)

    # ── feature_flags ─────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS feature_flags (
            flag_name   TEXT PRIMARY KEY,
            enabled     BOOLEAN NOT NULL DEFAULT FALSE,
            changed_by  TEXT NOT NULL DEFAULT 'system',
            changed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            reason      TEXT NOT NULL DEFAULT ''
        )
    """)

    # Seed from YAML defaults — safe values (all false for safety-critical)
    op.execute("""
        INSERT INTO feature_flags (flag_name, enabled, changed_by, reason)
        VALUES
            ('live_trading_enabled',    FALSE, 'system', 'Initial safe default'),
            ('paper_trading_enabled',   TRUE,  'system', 'Initial safe default'),
            ('websocket_enabled',       FALSE, 'system', 'Stage 2 — not yet implemented'),
            ('data_ingestion_enabled',  TRUE,  'system', 'Initial safe default'),
            ('alerting_enabled',        TRUE,  'system', 'Initial safe default'),
            ('prometheus_enabled',      TRUE,  'system', 'Initial safe default'),
            ('strategy_sma_enabled',    FALSE, 'system', 'Stage 3 — not yet implemented'),
            ('strategy_rsi_enabled',    FALSE, 'system', 'Stage 3 — not yet implemented'),
            ('canary_trade_enabled',    FALSE, 'system', 'Stage 5 — not yet implemented')
        ON CONFLICT (flag_name) DO NOTHING
    """)

    # ── idempotency_keys ──────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS idempotency_keys (
            key         TEXT PRIMARY KEY,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at  TIMESTAMPTZ NOT NULL,
            operation   TEXT NOT NULL DEFAULT 'unknown',
            actor       TEXT NOT NULL DEFAULT 'system'
        )
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_idempotency_keys_expires_at
        ON idempotency_keys (expires_at)
    """)

    # ── ohlcv_metadata ────────────────────────────────────────────────────
    # Tracks which Parquet partitions exist and their lineage.
    # The actual OHLCV data is in Parquet files, not in Postgres.
    op.execute("""
        CREATE TABLE IF NOT EXISTS ohlcv_metadata (
            id              BIGSERIAL PRIMARY KEY,
            exchange        TEXT NOT NULL,
            symbol          TEXT NOT NULL,
            timeframe       TEXT NOT NULL,
            year            SMALLINT NOT NULL,
            month           SMALLINT NOT NULL,
            parquet_path    TEXT NOT NULL,
            row_count       INTEGER NOT NULL DEFAULT 0,
            fetched_at      TIMESTAMPTZ NOT NULL,
            source          TEXT NOT NULL DEFAULT '',
            schema_version  TEXT NOT NULL DEFAULT '1.0',
            checksum        TEXT NOT NULL DEFAULT '',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS uix_ohlcv_metadata_partition
        ON ohlcv_metadata (exchange, symbol, timeframe, year, month)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ohlcv_metadata CASCADE")
    op.execute("DROP TABLE IF EXISTS idempotency_keys CASCADE")
    op.execute("DROP TABLE IF EXISTS feature_flags CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
