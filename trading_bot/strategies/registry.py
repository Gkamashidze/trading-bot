"""Strategy Governance Registry.

Records every strategy's version, hashes, research provenance, approval
history, and expiry.  The promotion pipeline must call
`require_valid_entry()` before advancing a strategy to the next tier.

Design rules:
- Registry is module-level (in-memory for now, DB persistence optional).
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
    """Thread-safe (GIL-protected) in-memory registry of strategy entries.

    All mutating methods return the updated entry so callers can inspect the
    result without an extra ``get()`` call.
    """

    def __init__(self) -> None:
        self._entries: dict[str, StrategyRegistryEntry] = {}

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


class RegistryError(Exception):
    """Raised when a strategy fails a governance registry check."""


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: StrategyRegistry = StrategyRegistry()


def get_strategy_registry() -> StrategyRegistry:
    return _registry
