"""Persistent Risk State Service — #5 of the production readiness roadmap.

Moves authoritative risk state out of process memory into a shared, persistent
store. Both the RiskEngine and the operator console read/write this store,
ensuring a single source of truth even across restarts.

Implementations:
  InMemoryRiskStateStore  — single-process, lost on restart (dev / no-DB fallback)
  PostgresRiskStateStore  — single-row upsert, survives restarts and multi-worker

All state changes are append-only from the caller's perspective; the store
records a timestamp and actor for each mutation to support audit replay.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    import asyncpg


class EmergencyHaltReason(StrEnum):
    OPERATOR_MANUAL = "operator_manual"
    LOSS_LIMIT_BREACH = "loss_limit_breach"
    RECONCILIATION_FAILURE = "reconciliation_failure"
    EXCHANGE_CONNECTIVITY = "exchange_connectivity"
    DRAWDOWN_LIMIT = "drawdown_limit"


@dataclass
class RiskStateSnapshot:
    """Complete, immutable snapshot of the risk state at a point in time.

    This is what the RiskEngine reads. All fields have explicit defaults so
    the engine starts in the most conservative (safe) state if the store is
    unavailable — fail closed.
    """

    # Strategy-level states
    strategy_states: dict[str, str] = field(default_factory=dict)
    # {"strategy_id": "active"|"paused"|"reduced_risk"}

    # Kill switch
    kill_switch_active: bool = False
    kill_switch_reason: str = ""
    kill_switch_activated_by: str = ""
    kill_switch_activated_at: datetime | None = None

    # Reconciler block
    reconciler_block_active: bool = False
    reconciler_block_reason: str = ""

    # Loss budgets (current period losses as positive USD amounts)
    daily_loss_usd: Decimal = Decimal("0")
    weekly_loss_usd: Decimal = Decimal("0")

    # Capital overrides (strategy_id → override capital pct, None = use policy default)
    capital_allocation_overrides: dict[str, float] = field(default_factory=dict)

    # Manual operator locks (free-form labels on locked resources)
    operator_locks: dict[str, str] = field(default_factory=dict)
    # e.g. {"BTC/USDT": "locked by alice for maintenance"}

    # Emergency halt
    emergency_halt_active: bool = False
    emergency_halt_reason: EmergencyHaltReason | None = None
    emergency_halt_at: datetime | None = None
    emergency_halt_by: str = ""

    # State metadata
    last_updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_updated_by: str = "system"
    version: int = 0

    @property
    def is_trading_globally_blocked(self) -> bool:
        """True if ANY global block is active — no order should proceed."""
        return self.kill_switch_active or self.reconciler_block_active or self.emergency_halt_active

    def to_dict(self) -> dict[str, Any]:
        return {
            "kill_switch_active": self.kill_switch_active,
            "reconciler_block_active": self.reconciler_block_active,
            "emergency_halt_active": self.emergency_halt_active,
            "strategy_states": dict(self.strategy_states),
            "daily_loss_usd": str(self.daily_loss_usd),
            "weekly_loss_usd": str(self.weekly_loss_usd),
            "last_updated_at": self.last_updated_at.isoformat(),
            "version": self.version,
        }


class RiskStateStore(ABC):
    """Abstract persistent store for the authoritative risk state.

    All mutations are idempotent and must record actor + reason for audit replay.
    Implementations must be safe for concurrent async access.
    """

    @abstractmethod
    async def get_snapshot(self) -> RiskStateSnapshot:
        """Return the current state. Must not raise — return safe defaults on failure."""

    @abstractmethod
    async def activate_kill_switch(self, reason: str, actor: str) -> None:
        """Activate the global kill switch."""

    @abstractmethod
    async def deactivate_kill_switch(self, actor: str) -> None:
        """Deactivate the kill switch."""

    @abstractmethod
    async def activate_emergency_halt(self, reason: EmergencyHaltReason, actor: str) -> None:
        """Activate a full emergency halt."""

    @abstractmethod
    async def clear_emergency_halt(self, actor: str) -> None:
        """Clear the emergency halt. Requires operator confirmation."""

    @abstractmethod
    async def set_reconciler_block(self, active: bool, reason: str, actor: str) -> None:
        """Set the reconciler block flag."""

    @abstractmethod
    async def set_strategy_state(self, strategy_id: str, state: str, actor: str) -> None:
        """Set allocation state for a strategy: 'active'|'paused'|'reduced_risk'."""

    @abstractmethod
    async def record_loss(self, loss_usd: Decimal, period: str) -> None:
        """Add a realized loss to the daily/weekly running total.

        period: 'daily' | 'weekly'
        """

    @abstractmethod
    async def reset_loss_budget(self, period: str, actor: str) -> None:
        """Reset the loss budget at period boundary (end of day/week)."""

    @abstractmethod
    async def set_capital_override(
        self, strategy_id: str, capital_pct: float | None, actor: str
    ) -> None:
        """Set or clear a per-strategy capital allocation override."""

    @abstractmethod
    async def set_operator_lock(self, resource: str, label: str, actor: str) -> None:
        """Lock a resource with an operator label."""

    @abstractmethod
    async def clear_operator_lock(self, resource: str, actor: str) -> None:
        """Release a resource lock."""


class InMemoryRiskStateStore(RiskStateStore):
    """In-process risk state store.

    Survives within a single process lifetime. Suitable for paper trading and
    single-process deployments. For multi-process or cross-restart persistence,
    use PostgresRiskStateStore (TODO — see ROADMAP.md Area #5).
    """

    def __init__(self) -> None:
        self._state = RiskStateSnapshot()
        self._lock = asyncio.Lock()

    async def get_snapshot(self) -> RiskStateSnapshot:
        async with self._lock:
            return RiskStateSnapshot(
                strategy_states=dict(self._state.strategy_states),
                kill_switch_active=self._state.kill_switch_active,
                kill_switch_reason=self._state.kill_switch_reason,
                kill_switch_activated_by=self._state.kill_switch_activated_by,
                kill_switch_activated_at=self._state.kill_switch_activated_at,
                reconciler_block_active=self._state.reconciler_block_active,
                reconciler_block_reason=self._state.reconciler_block_reason,
                daily_loss_usd=self._state.daily_loss_usd,
                weekly_loss_usd=self._state.weekly_loss_usd,
                capital_allocation_overrides=dict(self._state.capital_allocation_overrides),
                operator_locks=dict(self._state.operator_locks),
                emergency_halt_active=self._state.emergency_halt_active,
                emergency_halt_reason=self._state.emergency_halt_reason,
                emergency_halt_at=self._state.emergency_halt_at,
                emergency_halt_by=self._state.emergency_halt_by,
                last_updated_at=self._state.last_updated_at,
                last_updated_by=self._state.last_updated_by,
                version=self._state.version,
            )

    async def activate_kill_switch(self, reason: str, actor: str) -> None:
        async with self._lock:
            self._state.kill_switch_active = True
            self._state.kill_switch_reason = reason
            self._state.kill_switch_activated_by = actor
            self._state.kill_switch_activated_at = datetime.now(UTC)
            self._bump(actor)

    async def deactivate_kill_switch(self, actor: str) -> None:
        async with self._lock:
            self._state.kill_switch_active = False
            self._state.kill_switch_reason = ""
            self._bump(actor)

    async def activate_emergency_halt(self, reason: EmergencyHaltReason, actor: str) -> None:
        async with self._lock:
            self._state.emergency_halt_active = True
            self._state.emergency_halt_reason = reason
            self._state.emergency_halt_at = datetime.now(UTC)
            self._state.emergency_halt_by = actor
            self._bump(actor)

    async def clear_emergency_halt(self, actor: str) -> None:
        async with self._lock:
            self._state.emergency_halt_active = False
            self._state.emergency_halt_reason = None
            self._state.emergency_halt_at = None
            self._state.emergency_halt_by = ""
            self._bump(actor)

    async def set_reconciler_block(self, active: bool, reason: str, actor: str) -> None:
        async with self._lock:
            self._state.reconciler_block_active = active
            self._state.reconciler_block_reason = reason if active else ""
            self._bump(actor)

    async def set_strategy_state(self, strategy_id: str, state: str, actor: str) -> None:
        async with self._lock:
            self._state.strategy_states[strategy_id] = state
            self._bump(actor)

    async def record_loss(self, loss_usd: Decimal, period: str) -> None:
        async with self._lock:
            if period == "daily":
                self._state.daily_loss_usd += loss_usd
            elif period == "weekly":
                self._state.weekly_loss_usd += loss_usd
            self._bump("system")

    async def reset_loss_budget(self, period: str, actor: str) -> None:
        async with self._lock:
            if period == "daily":
                self._state.daily_loss_usd = Decimal("0")
            elif period == "weekly":
                self._state.weekly_loss_usd = Decimal("0")
            self._bump(actor)

    async def set_capital_override(
        self, strategy_id: str, capital_pct: float | None, actor: str
    ) -> None:
        async with self._lock:
            if capital_pct is None:
                self._state.capital_allocation_overrides.pop(strategy_id, None)
            else:
                self._state.capital_allocation_overrides[strategy_id] = capital_pct
            self._bump(actor)

    async def set_operator_lock(self, resource: str, label: str, actor: str) -> None:
        async with self._lock:
            self._state.operator_locks[resource] = label
            self._bump(actor)

    async def clear_operator_lock(self, resource: str, actor: str) -> None:
        async with self._lock:
            self._state.operator_locks.pop(resource, None)
            self._bump(actor)

    def _bump(self, actor: str) -> None:
        self._state.last_updated_at = datetime.now(UTC)
        self._state.last_updated_by = actor
        self._state.version += 1


class PostgresRiskStateStore(RiskStateStore):
    """Single-row Postgres risk state store (id=1).

    Survives process restarts. Call _ensure_row() once at startup to seed the row.
    Fails closed on DB errors — get_snapshot() returns safe defaults rather than raising.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def _ensure_row(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("INSERT INTO risk_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")

    async def get_snapshot(self) -> RiskStateSnapshot:
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow("SELECT * FROM risk_state WHERE id = 1")
            if row is None:
                return RiskStateSnapshot()
            halt_reason: EmergencyHaltReason | None = None
            if row["emergency_halt_reason"] is not None:
                try:
                    halt_reason = EmergencyHaltReason(row["emergency_halt_reason"])
                except ValueError:
                    pass
            return RiskStateSnapshot(
                strategy_states=dict(row["strategy_states"] or {}),
                kill_switch_active=row["kill_switch_active"],
                kill_switch_reason=row["kill_switch_reason"] or "",
                kill_switch_activated_by=row["kill_switch_activated_by"] or "",
                kill_switch_activated_at=row["kill_switch_activated_at"],
                reconciler_block_active=row["reconciler_block_active"],
                reconciler_block_reason=row["reconciler_block_reason"] or "",
                daily_loss_usd=Decimal(str(row["daily_loss_usd"])),
                weekly_loss_usd=Decimal(str(row["weekly_loss_usd"])),
                capital_allocation_overrides={
                    k: float(v) for k, v in (row["capital_allocation_overrides"] or {}).items()
                },
                operator_locks=dict(row["operator_locks"] or {}),
                emergency_halt_active=row["emergency_halt_active"],
                emergency_halt_reason=halt_reason,
                emergency_halt_at=row["emergency_halt_at"],
                emergency_halt_by=row["emergency_halt_by"] or "",
                last_updated_at=row["last_updated_at"] or datetime.now(UTC),
                last_updated_by=row["last_updated_by"] or "system",
                version=row["version"],
            )
        except Exception as exc:
            _log().warning("risk_state_get_failed", error=str(exc))
            return RiskStateSnapshot()

    async def activate_kill_switch(self, reason: str, actor: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE risk_state SET
                    kill_switch_active = TRUE, kill_switch_reason = $1,
                    kill_switch_activated_by = $2, kill_switch_activated_at = NOW(),
                    last_updated_at = NOW(), last_updated_by = $2, version = version + 1
                WHERE id = 1""",
                reason,
                actor,
            )

    async def deactivate_kill_switch(self, actor: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE risk_state SET
                    kill_switch_active = FALSE, kill_switch_reason = '',
                    kill_switch_activated_at = NULL,
                    last_updated_at = NOW(), last_updated_by = $1, version = version + 1
                WHERE id = 1""",
                actor,
            )

    async def activate_emergency_halt(self, reason: EmergencyHaltReason, actor: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE risk_state SET
                    emergency_halt_active = TRUE, emergency_halt_reason = $1,
                    emergency_halt_at = NOW(), emergency_halt_by = $2,
                    last_updated_at = NOW(), last_updated_by = $2, version = version + 1
                WHERE id = 1""",
                reason.value,
                actor,
            )

    async def clear_emergency_halt(self, actor: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE risk_state SET
                    emergency_halt_active = FALSE, emergency_halt_reason = NULL,
                    emergency_halt_at = NULL, emergency_halt_by = '',
                    last_updated_at = NOW(), last_updated_by = $1, version = version + 1
                WHERE id = 1""",
                actor,
            )

    async def set_reconciler_block(self, active: bool, reason: str, actor: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE risk_state SET
                    reconciler_block_active = $1, reconciler_block_reason = $2,
                    last_updated_at = NOW(), last_updated_by = $3, version = version + 1
                WHERE id = 1""",
                active,
                reason if active else "",
                actor,
            )

    async def set_strategy_state(self, strategy_id: str, state: str, actor: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE risk_state SET
                    strategy_states = strategy_states
                        || jsonb_build_object($1::text, $2::text),
                    last_updated_at = NOW(), last_updated_by = $3, version = version + 1
                WHERE id = 1""",
                strategy_id,
                state,
                actor,
            )

    _RECORD_LOSS_SQL: ClassVar[dict[str, str]] = {
        "daily": """UPDATE risk_state SET
            daily_loss_usd = daily_loss_usd + $1,
            last_updated_at = NOW(), last_updated_by = 'system', version = version + 1
        WHERE id = 1""",
        "weekly": """UPDATE risk_state SET
            weekly_loss_usd = weekly_loss_usd + $1,
            last_updated_at = NOW(), last_updated_by = 'system', version = version + 1
        WHERE id = 1""",
    }

    _RESET_LOSS_SQL: ClassVar[dict[str, str]] = {
        "daily": """UPDATE risk_state SET
            daily_loss_usd = 0,
            last_updated_at = NOW(), last_updated_by = $1, version = version + 1
        WHERE id = 1""",
        "weekly": """UPDATE risk_state SET
            weekly_loss_usd = 0,
            last_updated_at = NOW(), last_updated_by = $1, version = version + 1
        WHERE id = 1""",
    }

    async def record_loss(self, loss_usd: Decimal, period: str) -> None:
        sql = self._RECORD_LOSS_SQL.get(period)
        if sql is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(sql, loss_usd)

    async def reset_loss_budget(self, period: str, actor: str) -> None:
        sql = self._RESET_LOSS_SQL.get(period)
        if sql is None:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(sql, actor)

    async def set_capital_override(
        self, strategy_id: str, capital_pct: float | None, actor: str
    ) -> None:
        async with self._pool.acquire() as conn:
            if capital_pct is None:
                await conn.execute(
                    """UPDATE risk_state SET
                        capital_allocation_overrides = capital_allocation_overrides - $1,
                        last_updated_at = NOW(), last_updated_by = $2, version = version + 1
                    WHERE id = 1""",
                    strategy_id,
                    actor,
                )
            else:
                await conn.execute(
                    """UPDATE risk_state SET
                        capital_allocation_overrides = capital_allocation_overrides
                            || jsonb_build_object($1::text, $2::float8),
                        last_updated_at = NOW(), last_updated_by = $3, version = version + 1
                    WHERE id = 1""",
                    strategy_id,
                    capital_pct,
                    actor,
                )

    async def set_operator_lock(self, resource: str, label: str, actor: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE risk_state SET
                    operator_locks = operator_locks
                        || jsonb_build_object($1::text, $2::text),
                    last_updated_at = NOW(), last_updated_by = $3, version = version + 1
                WHERE id = 1""",
                resource,
                label,
                actor,
            )

    async def clear_operator_lock(self, resource: str, actor: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """UPDATE risk_state SET
                    operator_locks = operator_locks - $1,
                    last_updated_at = NOW(), last_updated_by = $2, version = version + 1
                WHERE id = 1""",
                resource,
                actor,
            )


def _log() -> Any:
    from trading_bot.observability.logging import get_logger

    return get_logger(__name__)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_risk_state_store: RiskStateStore | None = None


def get_risk_state_store() -> RiskStateStore:
    """Return the module-level RiskStateStore singleton."""
    global _risk_state_store
    if _risk_state_store is None:
        _risk_state_store = InMemoryRiskStateStore()
    return _risk_state_store


def set_risk_state_store(store: RiskStateStore) -> None:
    """Replace the singleton (used in tests and at startup when Postgres is available)."""
    global _risk_state_store
    _risk_state_store = store
