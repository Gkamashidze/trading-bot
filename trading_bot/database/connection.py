"""asyncpg connection pool management.

One pool per process. Created at startup, closed on shutdown.
Access via the get_pool() module-level function after calling init_pool().
"""

from __future__ import annotations

import asyncpg

from trading_bot.observability.logging import get_logger
from trading_bot.observability.metrics import DB_POOL_UTILIZATION

log = get_logger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool(
    database_url: str,
    min_size: int = 5,
    max_size: int = 20,
    command_timeout: float = 30.0,
) -> asyncpg.Pool:
    """Create the global asyncpg connection pool. Call once at startup."""
    global _pool

    # Strip the +asyncpg driver suffix if present (SQLAlchemy adds it for Alembic)
    dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")

    _pool = await asyncpg.create_pool(
        dsn=dsn,
        min_size=min_size,
        max_size=max_size,
        command_timeout=command_timeout,
    )

    log.info("db_pool_created", min_size=min_size, max_size=max_size)
    return _pool


async def close_pool() -> None:
    """Close the global connection pool gracefully. Call on shutdown."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
        log.info("db_pool_closed")


def get_pool() -> asyncpg.Pool:
    """Return the active pool. Raises RuntimeError if pool is not initialised."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialised. Call init_pool() at startup.")
    return _pool


async def update_pool_metrics() -> None:
    """Update Prometheus gauge for DB connection pool utilization."""
    if _pool is not None:
        utilization = (_pool.get_size() - _pool.get_idle_size()) / max(_pool.get_size(), 1)
        DB_POOL_UTILIZATION.set(utilization)
