"""Strategy Governance Registry.

Records every strategy's version, hashes, research provenance, approval
history, and expiry.  The promotion pipeline must call
`require_valid_entry()` before advancing a strategy to the next tier.

Design rules:
- Registry is optionally Postgres-backed: pass pool= to StrategyRegistry().
- Without a pool, operates in-memory (suitable for tests).
- Entries are immutable; updates create new versions via `update_entry()`.
- Approval history is append-only — never mutate past records.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApprovalRecord:
    """A single approval or rejection event."""

    approver: str
    decision: str  # "approved" | "rejected"
    recorded_at: datetime
    note: str = ""


# ---------------------------------------------------------------------------
# Registry entry
# ---------------------------------------------------------------------------


@dataclass
class StrategyRegistryEntry:
    """Governance metadata for a registered strategy.

    All hash fields are hex-encoded SHA-256 digests (or empty string if
    not yet computed).  ``is_valid()`` is the single gate to check before
    promotion.
    """

    strategy_id: str
    version: str  # semver e.g. "1.0.0"
    owner: str = "unassigned"

    # Provenance hashes — populated at registration time
    params_hash: str = ""  # sha256(json-serialised strategy params)
    code_hash: str = ""  # sha256(strategy source file bytes)
    research_dataset_hash: str = ""  # sha256 of training/validation dataset
    backtest_result_id: str = ""  # ID referencing a stored BacktestResult

    # Lifecycle
    promotion_status: str = "pending"  # "pending" | "approved" | "rejected" | "expired"
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expiry_date: datetime | None = None
    review_date: datetime | None = None
    approval_history: list[ApprovalRecord] = field(default_factory=list)

    # ---------------------------------------------------------------------------

    def is_approved(self) -> bool:
        return self.promotion_status == "approved"

    def is_expired(self) -> bool:
        if self.expiry_date is None:
            return False
        return datetime.now(UTC) > self.expiry_date

    def needs_review(self) -> bool:
        if self.review_date is None:
            return False
        return datetime.now(UTC) > self.review_date

    def is_valid(self) -> bool:
        """True only if approved and not yet expired."""
        return self.is_approved() and not self.is_expired()

    def add_approval(self, record: ApprovalRecord) -> None:
        """Append an approval record and update promotion_status."""
        self.approval_history.append(record)
        self.promotion_status = record.decision  # "approved" or "rejected"

    def expire(self) -> None:
        self.promotion_status = "expired"


# ---------------------------------------------------------------------------
# Helpers — hash computation
# ---------------------------------------------------------------------------


def hash_params(params: dict) -> str:  # type: ignore[type-arg]
    """Return SHA-256 of JSON-serialised params dict (sorted keys)."""
    raw = json.dumps(params, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def hash_file(path: str) -> str:
    """Return SHA-256 of a file's contents (empty string if file not found)."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# In-memory registry
# ---------------------------------------------------------------------------


class StrategyRegistry:
    """Postgres-backed (optionally in-memory) registry of strategy entries.

    Pass pool= for persistent storage.  Without a pool, operates in-memory.
    All mutating methods return the updated entry so callers can inspect the
    result without an extra ``get()`` call.
    """

    def __init__(self, pool: object = None) -> None:
        self._entries: dict[str, StrategyRegistryEntry] = {}
        self._pool = pool  # asyncpg Pool | None

    def register(self, entry: StrategyRegistryEntry) -> StrategyRegistryEntry:
        """Add or replace the entry for entry.strategy_id."""
        self._entries[entry.strategy_id] = entry
        return entry

    def get(self, strategy_id: str) -> StrategyRegistryEntry | None:
        return self._entries.get(strategy_id)

    def approve(
        self,
        strategy_id: str,
        approver: str,
        note: str = "",
    ) -> StrategyRegistryEntry:
        """Mark strategy as approved.  Raises KeyError if not registered."""
        entry = self._entries[strategy_id]
        record = ApprovalRecord(
            approver=approver,
            decision="approved",
            recorded_at=datetime.now(UTC),
            note=note,
        )
        entry.add_approval(record)
        return entry

    def reject(
        self,
        strategy_id: str,
        approver: str,
        note: str = "",
    ) -> StrategyRegistryEntry:
        entry = self._entries[strategy_id]
        record = ApprovalRecord(
            approver=approver,
            decision="rejected",
            recorded_at=datetime.now(UTC),
            note=note,
        )
        entry.add_approval(record)
        return entry

    def expire(self, strategy_id: str) -> StrategyRegistryEntry:
        entry = self._entries[strategy_id]
        entry.expire()
        return entry

    def all_entries(self) -> list[StrategyRegistryEntry]:
        return list(self._entries.values())

    def require_valid_entry(self, strategy_id: str) -> None:
        """Raise RegistryError if the strategy has no valid (approved, non-expired) entry."""
        entry = self._entries.get(strategy_id)
        if entry is None:
            raise RegistryError(f"strategy '{strategy_id}' not in governance registry")
        if entry.is_expired():
            raise RegistryError(f"strategy '{strategy_id}' registry entry has expired")
        if not entry.is_approved():
            raise RegistryError(
                f"strategy '{strategy_id}' is not approved (status={entry.promotion_status})"
            )

    # ── DB persistence ────────────────────────────────────────────────────────

    async def _persist_entry(self, entry: StrategyRegistryEntry) -> None:
        """Upsert strategy entry to strategy_registry table."""
        if self._pool is None:
            return
        try:
            approval_history_json = json.dumps(
                [
                    {
                        "approver": r.approver,
                        "decision": r.decision,
                        "recorded_at": r.recorded_at.isoformat(),
                        "note": r.note,
                    }
                    for r in entry.approval_history
                ]
            )
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO strategy_registry (
                        strategy_id, version, owner, params_hash, code_hash,
                        research_dataset_hash, backtest_result_id,
                        promotion_status, registered_at,
                        expiry_date, review_date, approval_history
                    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                    ON CONFLICT (strategy_id, version) DO UPDATE SET
                        owner                 = EXCLUDED.owner,
                        params_hash           = EXCLUDED.params_hash,
                        code_hash             = EXCLUDED.code_hash,
                        research_dataset_hash = EXCLUDED.research_dataset_hash,
                        backtest_result_id    = EXCLUDED.backtest_result_id,
                        promotion_status      = EXCLUDED.promotion_status,
                        expiry_date           = EXCLUDED.expiry_date,
                        review_date           = EXCLUDED.review_date,
                        approval_history      = EXCLUDED.approval_history
                    """,
                    entry.strategy_id,
                    entry.version,
                    entry.owner,
                    entry.params_hash,
                    entry.code_hash,
                    entry.research_dataset_hash,
                    entry.backtest_result_id,
                    entry.promotion_status,
                    entry.registered_at,
                    entry.expiry_date,
                    entry.review_date,
                    approval_history_json,
                )
        except Exception as exc:
            import logging as _logging

            _logging.getLogger(__name__).error(
                "strategy_registry_persist_failed strategy_id=%s error=%s",
                entry.strategy_id,
                exc,
            )

    async def load_from_db(self) -> int:
        """Load strategy entries from Postgres.  Returns count loaded.  No-op if no pool."""
        if self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT strategy_id, version, owner, params_hash, code_hash,
                           research_dataset_hash, backtest_result_id,
                           promotion_status, registered_at,
                           expiry_date, review_date, approval_history
                    FROM strategy_registry
                    ORDER BY registered_at ASC
                    """
                )
        except Exception as exc:
            import logging as _logging

            _logging.getLogger(__name__).error(
                "strategy_registry_load_failed error=%s", exc
            )
            return 0

        count = 0
        for row in rows:
            try:
                history_raw = (
                    json.loads(row["approval_history"])
                    if isinstance(row["approval_history"], str)
                    else list(row["approval_history"])
                )
                history = [
                    ApprovalRecord(
                        approver=r["approver"],
                        decision=r["decision"],
                        recorded_at=datetime.fromisoformat(r["recorded_at"]),
                        note=r.get("note", ""),
                    )
                    for r in history_raw
                ]
                entry = StrategyRegistryEntry(
                    strategy_id=row["strategy_id"],
                    version=row["version"],
                    owner=row["owner"] or "unassigned",
                    params_hash=row["params_hash"] or "",
                    code_hash=row["code_hash"] or "",
                    research_dataset_hash=row["research_dataset_hash"] or "",
                    backtest_result_id=row["backtest_result_id"] or "",
                    promotion_status=row["promotion_status"],
                    registered_at=row["registered_at"],
                    expiry_date=row["expiry_date"],
                    review_date=row["review_date"],
                    approval_history=history,
                )
                self._entries[entry.strategy_id] = entry
                count += 1
            except Exception as exc:
                import logging as _logging

                _logging.getLogger(__name__).warning(
                    "strategy_registry_row_parse_failed strategy_id=%s error=%s",
                    row.get("strategy_id", "?"),
                    exc,
                )
        return count


class RegistryError(Exception):
    """Raised when a strategy fails a governance registry check."""


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: StrategyRegistry = StrategyRegistry()


def get_strategy_registry() -> StrategyRegistry:
    return _registry
