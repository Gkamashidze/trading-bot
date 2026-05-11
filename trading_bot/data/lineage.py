"""Dataset snapshot store — immutable IDs for backtesting provenance.

Every batch of market data that enters a backtest or research run is
registered here as an immutable ``DatasetSnapshot``.  The snapshot ID
is the single reference that ties a backtest result to the exact data
it was run against.

Usage:
    store = get_lineage_store()
    sid = store.create_snapshot(lineage)          # register and get ID
    snap = store.get_snapshot(sid)                # retrieve by ID
    store.verify_snapshot(sid, lineage)           # raises if mismatch
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from trading_bot.core.models import DataLineage
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Snapshot record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DatasetSnapshot:
    """Immutable record of a dataset at a point in time."""

    snapshot_id: str  # sha256 of canonical lineage JSON
    lineage: DataLineage
    created_at: datetime


# ---------------------------------------------------------------------------
# Snapshot verification
# ---------------------------------------------------------------------------


class SnapshotMismatchError(Exception):
    """Raised when a stored snapshot does not match the supplied lineage."""


def _snapshot_id(lineage: DataLineage) -> str:
    """Compute a deterministic snapshot ID from the lineage fields.

    Uses a stable subset of fields — excludes processed_at (may differ
    between runs) and quarantine fields (post-processing metadata).
    """
    key = {
        "source": lineage.source,
        "fetched_at": lineage.fetched_at.isoformat(),
        "schema_version": lineage.schema_version,
        "row_count": lineage.row_count,
        "checksum": lineage.checksum,
        "provider": lineage.provider,
        "exchange": lineage.exchange,
        "symbol": lineage.symbol,
        "timeframe": lineage.timeframe,
        "storage_path": lineage.storage_path,
    }
    raw = json.dumps(key, sort_keys=True).encode()
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------


class LineageStore:
    """In-memory store of dataset snapshots.

    Thread-safe (GIL-protected).  Snapshots are immutable after creation.

    Note: process-local and lost on restart. See ADR-0009 for the
    PostgreSQL-backed migration plan, triggered when Stage 5 begins or
    cross-restart provenance is required.
    """

    def __init__(self) -> None:
        self._snapshots: dict[str, DatasetSnapshot] = {}

    def create_snapshot(self, lineage: DataLineage) -> str:
        """Register a lineage record and return its snapshot ID.

        Idempotent: calling with identical lineage returns the same ID.
        """
        sid = _snapshot_id(lineage)
        if sid not in self._snapshots:
            snap = DatasetSnapshot(
                snapshot_id=sid,
                lineage=lineage,
                created_at=datetime.now(UTC),
            )
            self._snapshots[sid] = snap
            log.info(
                "dataset_snapshot_created",
                snapshot_id=sid,
                symbol=lineage.symbol,
                timeframe=lineage.timeframe,
                row_count=lineage.row_count,
            )
        return sid

    def get_snapshot(self, snapshot_id: str) -> DatasetSnapshot | None:
        return self._snapshots.get(snapshot_id)

    def verify_snapshot(self, snapshot_id: str, lineage: DataLineage) -> None:
        """Raise SnapshotMismatchError if stored snapshot doesn't match lineage.

        Raises KeyError if the snapshot_id is unknown.
        """
        stored = self._snapshots.get(snapshot_id)
        if stored is None:
            raise KeyError(f"unknown snapshot_id: {snapshot_id}")

        computed = _snapshot_id(lineage)
        if computed != snapshot_id:
            raise SnapshotMismatchError(
                f"snapshot mismatch: stored={snapshot_id[:12]}... computed={computed[:12]}..."
            )

    def all_snapshots(self) -> list[DatasetSnapshot]:
        return list(self._snapshots.values())

    def __len__(self) -> int:
        return len(self._snapshots)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_store: LineageStore = LineageStore()


def get_lineage_store() -> LineageStore:
    return _store
