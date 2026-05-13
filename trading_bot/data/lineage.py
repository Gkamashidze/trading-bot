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
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from trading_bot.core.models import DataLineage
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_LINEAGE_PATH = Path(os.environ.get("DATA_PATH", "data/raw")).parent / "lineage_store.json"


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
    """Dataset snapshot store with disk persistence.

    Snapshots are immutable after creation and keyed by sha256 of their
    content, making the store self-verifying and safe to merge across restarts.
    Persisted to ``persist_path`` (atomic write) so backtests survive restarts
    without re-running a backfill.

    Pass ``persist_path=None`` to disable persistence (used in tests).
    """

    def __init__(self, persist_path: Path | None = _LINEAGE_PATH) -> None:
        self._snapshots: dict[str, DatasetSnapshot] = {}
        self._persist_path = persist_path
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self._persist_path is None:
            return
        try:
            if self._persist_path.exists():
                raw: dict[str, dict[str, object]] = json.loads(self._persist_path.read_text())
                for sid, entry in raw.items():
                    lineage = DataLineage.model_validate(entry["lineage"])
                    snap = DatasetSnapshot(
                        snapshot_id=sid,
                        lineage=lineage,
                        created_at=datetime.fromisoformat(str(entry["created_at"])),
                    )
                    self._snapshots[sid] = snap
                log.info("lineage_store_loaded", path=str(self._persist_path), count=len(raw))
        except Exception as exc:
            log.warning(
                "lineage_store_load_failed", path=str(self._persist_path), error=str(exc)
            )

    def _save_to_disk(self) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._persist_path.with_suffix(".json.tmp")
            data = {
                sid: {
                    "created_at": snap.created_at.isoformat(),
                    "lineage": snap.lineage.model_dump(mode="json"),
                }
                for sid, snap in self._snapshots.items()
            }
            tmp.write_text(json.dumps(data))
            tmp.replace(self._persist_path)
        except Exception as exc:
            log.warning(
                "lineage_store_save_failed", path=str(self._persist_path), error=str(exc)
            )

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
            self._save_to_disk()
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
