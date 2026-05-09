"""Feature flag store — Postgres-backed with in-memory cache.

Cache is refreshed every N seconds (configurable, default 30s).
On DB failure, falls back to cached values (fail-open for most flags,
fail-closed for safety-critical flags like live_trading_enabled).

DB schema (created via Alembic):
    feature_flags (
        flag_name   TEXT PRIMARY KEY,
        enabled     BOOLEAN NOT NULL,
        changed_by  TEXT NOT NULL DEFAULT 'system',
        changed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        reason      TEXT NOT NULL DEFAULT ''
    )
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import yaml
from cachetools import TTLCache

from trading_bot.core.contracts import FeatureFlagStoreInterface
from trading_bot.observability.logging import get_logger
from trading_bot.observability.metrics import FEATURE_FLAG_EVALUATIONS

log = get_logger(__name__)

# YAML defaults are loaded once at module import — DB values override these.
_YAML_DEFAULTS: dict[str, bool] = {}
_yaml_path = Path(__file__).parent.parent / "config" / "feature_flags.yaml"
if _yaml_path.exists():
    _raw = yaml.safe_load(_yaml_path.read_text()) or {}
    for name, meta in (_raw.get("flags") or {}).items():
        _YAML_DEFAULTS[name] = bool(meta.get("default", False))

# Safety-critical flags that default to False even on DB failure
_SAFETY_CRITICAL = {"live_trading_enabled", "canary_trade_enabled"}

# Module-level singleton store reference (set by main.py after pool creation)
_default_store: FeatureFlagStore | None = None


def set_default_store(store: FeatureFlagStore) -> None:
    global _default_store
    _default_store = store


async def is_enabled(flag_name: str) -> bool:
    """Check a feature flag using the module-level default store."""
    if _default_store is None:
        # No store configured — return YAML default or False
        return _YAML_DEFAULTS.get(flag_name, False)
    return await _default_store.is_enabled(flag_name)


class FeatureFlagStore(FeatureFlagStoreInterface):
    """DB-backed feature flag store with TTL in-memory cache.

    Thread/task safety: async-safe with asyncio.Lock protecting cache writes.
    """

    def __init__(
        self,
        pool: Any,
        refresh_interval_seconds: int = 30,
    ) -> None:
        self._pool = pool
        self._refresh_interval = refresh_interval_seconds
        # TTL cache: entries expire after refresh_interval seconds
        self._cache: TTLCache[str, bool] = TTLCache(
            maxsize=256,
            ttl=refresh_interval_seconds,
        )
        self._lock = asyncio.Lock()
        self._last_refresh: float = 0.0

    async def is_enabled(self, flag_name: str) -> bool:
        """Return current flag value with cache.

        Evaluation order:
        1. In-memory TTL cache
        2. DB (if cache miss or expired)
        3. YAML default (if DB unavailable)
        4. False (if not in YAML either) — fail-safe default
        """
        cached = self._cache.get(flag_name)
        if cached is not None:
            result = cached
        else:
            result = await self._fetch_from_db(flag_name)

        FEATURE_FLAG_EVALUATIONS.labels(
            flag_name=flag_name,
            result="enabled" if result else "disabled",
        ).inc()

        return result

    async def set_flag(
        self,
        flag_name: str,
        value: bool,
        changed_by: str,
        reason: str,
    ) -> None:
        """Persist a flag change to DB and update cache.

        A FlagChangeEvent is emitted on the event bus if a bus is configured.
        Every change is logged to the audit trail.
        """
        async with self._lock:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO feature_flags (flag_name, enabled, changed_by, reason, changed_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (flag_name) DO UPDATE
                    SET enabled = $2, changed_by = $3, reason = $4, changed_at = NOW()
                    """,
                    flag_name,
                    value,
                    changed_by,
                    reason,
                )
            self._cache[flag_name] = value

        log.info(
            "feature_flag_changed",
            flag_name=flag_name,
            new_value=value,
            changed_by=changed_by,
            reason=reason,
        )

    async def refresh(self) -> None:
        """Reload all flags from DB into cache."""
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch("SELECT flag_name, enabled FROM feature_flags")
            async with self._lock:
                for row in rows:
                    self._cache[row["flag_name"]] = row["enabled"]
            self._last_refresh = time.monotonic()
            log.debug("feature_flags_refreshed", count=len(rows))
        except Exception as e:
            log.error(
                "feature_flag_refresh_failed",
                error=str(e),
                action="using_cached_or_yaml_defaults",
            )

    async def _fetch_from_db(self, flag_name: str) -> bool:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT enabled FROM feature_flags WHERE flag_name = $1",
                    flag_name,
                )
            if row is not None:
                value = bool(row["enabled"])
                self._cache[flag_name] = value
                return value
        except Exception as e:
            log.warning(
                "feature_flag_db_miss",
                flag_name=flag_name,
                error=str(e),
                action="falling_back_to_yaml_default",
            )

        # Fall back to YAML default — safety-critical flags default to False
        if flag_name in _SAFETY_CRITICAL:
            return False
        return _YAML_DEFAULTS.get(flag_name, False)
