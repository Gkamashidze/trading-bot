"""Append-only, hash-chained audit log (Postgres-backed).

Every significant event is appended here. The chain prevents silent
tampering: each event stores a SHA-256 hash of (prev_hash + payload),
so any modification to a past event breaks all subsequent hashes.

This is NOT a replacement for structured logging (structlog). The audit
log is for *regulatory* and *replay* purposes. Structlog is for
*operational* observability.

DB schema (Alembic migration):
    audit_log (
        event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        event_type      TEXT NOT NULL,
        schema_version  TEXT NOT NULL DEFAULT '1.0',
        occurred_at     TIMESTAMPTZ NOT NULL,
        correlation_id  TEXT NOT NULL DEFAULT '',
        actor           TEXT NOT NULL DEFAULT 'system',
        payload         JSONB NOT NULL,
        prev_event_hash TEXT,
        event_hash      TEXT NOT NULL,
        config_snapshot JSONB NOT NULL DEFAULT '{}'
    )

Partition: monthly (audit_log_YYYY_MM) — see Alembic migration.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

import asyncpg
import orjson

from trading_bot.core.contracts import AuditLogInterface
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


def _compute_hash(prev_hash: str | None, payload_bytes: bytes) -> str:
    """Compute SHA-256 hash for the event chain link."""
    data = (prev_hash or "GENESIS").encode() + payload_bytes
    return hashlib.sha256(data).hexdigest()


class PostgresAuditLog(AuditLogInterface):
    """Append-only audit log backed by PostgreSQL.

    Chain integrity:
    - Each event stores prev_event_hash (pointer to previous)
    - Each event stores event_hash = sha256(prev_hash + payload)
    - verify_chain() replays the chain and recomputes all hashes

    WORM semantics: no UPDATE or DELETE on audit_log is permitted.
    Enforce via Postgres row-level security or a dedicated DB role
    that only has INSERT + SELECT privileges on this table.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str = "",
        actor: str = "system",
        occurred_at: datetime | None = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> str:
        """Append an event. Returns the event_hash for this entry."""
        if occurred_at is None:
            occurred_at = datetime.now(timezone.utc)

        payload_bytes = orjson.dumps(payload, option=orjson.OPT_SORT_KEYS)
        prev_hash = await self.get_chain_head()
        event_hash = _compute_hash(prev_hash, payload_bytes)

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (
                    event_type, schema_version, occurred_at,
                    correlation_id, actor, payload,
                    prev_event_hash, event_hash, config_snapshot
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                event_type,
                "1.0",
                occurred_at,
                correlation_id,
                actor,
                json.dumps(payload),
                prev_hash,
                event_hash,
                json.dumps(config_snapshot or {}),
            )

        log.debug(
            "audit_log_appended",
            event_type=event_type,
            correlation_id=correlation_id,
            hash_prefix=event_hash[:8],
        )
        return event_hash

    async def get_chain_head(self) -> str | None:
        """Return the hash of the most recently appended event."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT event_hash FROM audit_log ORDER BY occurred_at DESC LIMIT 1"
            )
        return row["event_hash"] if row else None

    async def verify_chain(self, since_event_id: str | None = None) -> bool:
        """Verify hash chain integrity.

        Reads events in chronological order and recomputes hashes.
        Returns True if the chain is intact; False if any link is broken.

        WARNING: This is an O(n) operation on the full audit log.
        Run periodically (daily) on a read replica — not on the hot path.
        """
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT event_id, payload, prev_event_hash, event_hash
                FROM audit_log
                ORDER BY occurred_at ASC
                """
            )

        expected_prev: str | None = None
        for row in rows:
            payload_bytes = (
                row["payload"].encode() if isinstance(row["payload"], str) else row["payload"]
            )
            recomputed = _compute_hash(row["prev_event_hash"], payload_bytes)
            if recomputed != row["event_hash"]:
                log.error(
                    "audit_chain_integrity_violation",
                    event_id=str(row["event_id"]),
                    expected_hash=recomputed,
                    stored_hash=row["event_hash"],
                )
                return False
            expected_prev = row["event_hash"]

        log.info("audit_chain_verified", events_checked=len(rows))
        return True
