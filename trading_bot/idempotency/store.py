"""Postgres-backed idempotency key store.

Schema (created via Alembic migration):
    idempotency_keys (
        key         TEXT PRIMARY KEY,
        created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        expires_at  TIMESTAMPTZ NOT NULL,
        operation   TEXT NOT NULL,
        actor       TEXT NOT NULL DEFAULT ''
    )

TTL: 7 days (604800 seconds). Old keys are cleaned up by a scheduled job.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from trading_bot.core.contracts import IdempotencyStoreInterface
from trading_bot.core.exceptions import IdempotencyCollisionError
from trading_bot.observability.logging import get_logger
from trading_bot.observability.metrics import IDEMPOTENCY_HITS

log = get_logger(__name__)

_DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days


class PostgresIdempotencyStore(IdempotencyStoreInterface):
    """Postgres-backed idempotency store.

    Requires an asyncpg connection pool to be provided at construction time.
    The store is NOT a singleton — one instance per pool.
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    async def acquire(self, key: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> bool:
        """Attempt to acquire the idempotency key.

        Returns True if this is the first time the key is seen (within TTL).
        Returns False if the key already exists — caller should treat this as a duplicate.

        Uses INSERT ... ON CONFLICT DO NOTHING for atomicity under concurrent access.
        """
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)

        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                INSERT INTO idempotency_keys (key, expires_at, operation)
                VALUES ($1, $2, $3)
                ON CONFLICT (key) DO NOTHING
                """,
                key,
                expires_at,
                "unknown",  # caller can override via set_operation()
            )

        # "INSERT 0 0" means conflict (duplicate) — "INSERT 0 1" means inserted
        acquired: bool = result == "INSERT 0 1"
        if not acquired:
            IDEMPOTENCY_HITS.inc()
            log.warning(
                "idempotency_collision",
                key=key[:16] + "...",  # log prefix only — not full key
                action="blocked_duplicate",
            )
        return acquired

    async def acquire_or_raise(self, key: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        """Acquire key or raise IdempotencyCollisionError on duplicate."""
        if not await self.acquire(key, ttl_seconds):
            raise IdempotencyCollisionError(
                f"Duplicate operation detected. Idempotency key already exists: {key[:16]}..."
            )

    async def release(self, key: str) -> None:
        """Explicitly delete a key (e.g. after confirmed failure that should be retried)."""
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM idempotency_keys WHERE key = $1",
                key,
            )
        log.info("idempotency_key_released", key=key[:16] + "...")

    async def cleanup_expired(self) -> int:
        """Delete expired keys. Should be called by a scheduled job daily."""
        async with self._pool.acquire() as conn:
            result = await conn.execute("DELETE FROM idempotency_keys WHERE expires_at < NOW()")
        deleted = int(result.split()[-1])
        log.info("idempotency_keys_cleaned", deleted=deleted)
        return deleted
