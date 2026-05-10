"""Reproducible Research Workflow — Feature #7.

Every research run is captured as an ExperimentArtifact with:
  - a unique experiment ID
  - references to the exact dataset snapshots used
  - a hash of the strategy parameters and code
  - a deterministic PRNG seed for reproducibility
  - performance metrics
  - approval status (DRAFT → APPROVED → ARCHIVED)

This makes backtests fully reproducible and auditable: given an
experiment ID you can re-run with the same data, same code, same seed.

Usage:
    registry = get_experiment_registry()
    exp = registry.create(
        strategy_id="sma_crossover",
        dataset_snapshot_ids=["abc123", "def456"],
        params_hash="...",
        code_hash="...",
        seed=42,
        metrics={"sharpe": 1.4, "max_dd": 0.08},
    )
    registry.approve(exp.experiment_id, approved_by="quant_team")
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_background_tasks: set[asyncio.Task] = set()


def _schedule_persist(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(coro)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    ARCHIVED = "archived"


# ---------------------------------------------------------------------------
# Immutable artifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExperimentArtifact:
    """Immutable record of a single research/backtest run."""

    experiment_id: str
    strategy_id: str
    dataset_snapshot_ids: tuple[str, ...]  # lineage snapshot IDs from data.lineage
    params_hash: str  # SHA-256 of strategy parameters JSON
    code_hash: str  # SHA-256 of strategy source file
    seed: int  # PRNG seed for deterministic replay
    metrics: dict[str, float]  # {"sharpe": 1.4, "max_dd": 0.08, ...}
    created_at: datetime
    status: ExperimentStatus = ExperimentStatus.DRAFT
    approved_by: str = ""
    approved_at: datetime | None = None
    notes: str = ""

    @property
    def is_approved(self) -> bool:
        return self.status == ExperimentStatus.APPROVED

    @property
    def fingerprint(self) -> str:
        """Deterministic ID combining params + code + seed + datasets."""
        key = {
            "params_hash": self.params_hash,
            "code_hash": self.code_hash,
            "seed": self.seed,
            "snapshots": sorted(self.dataset_snapshot_ids),
        }
        raw = json.dumps(key, sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ExperimentRegistry:
    """Store of experiment artifacts backed by an optional Postgres pool.

    Without a pool, operates as an in-memory store (suitable for tests).
    With a pool, all mutations are persisted to the ``experiments`` table and
    the registry can be reloaded after a process restart via ``load_from_db()``.

    Experiments are append-only; approval/archival create updated copies.
    """

    def __init__(self, pool: object = None) -> None:
        self._store: dict[str, ExperimentArtifact] = {}
        self._pool = pool  # asyncpg Pool | None

    def create(
        self,
        strategy_id: str,
        dataset_snapshot_ids: list[str],
        params_hash: str,
        code_hash: str,
        seed: int,
        metrics: dict[str, float],
        notes: str = "",
    ) -> ExperimentArtifact:
        artifact = ExperimentArtifact(
            experiment_id=str(uuid.uuid4()),
            strategy_id=strategy_id,
            dataset_snapshot_ids=tuple(sorted(dataset_snapshot_ids)),
            params_hash=params_hash,
            code_hash=code_hash,
            seed=seed,
            metrics=dict(metrics),
            created_at=datetime.now(UTC),
            status=ExperimentStatus.DRAFT,
            notes=notes,
        )
        self._store[artifact.experiment_id] = artifact
        log.info(
            "experiment_created",
            experiment_id=artifact.experiment_id,
            strategy_id=strategy_id,
            fingerprint=artifact.fingerprint[:12],
        )
        _schedule_persist(self._persist(artifact))
        return artifact

    def approve(self, experiment_id: str, approved_by: str) -> ExperimentArtifact:
        """Transition experiment from DRAFT to APPROVED."""
        artifact = self._get_or_raise(experiment_id)
        if artifact.status == ExperimentStatus.APPROVED:
            return artifact

        updated = ExperimentArtifact(
            experiment_id=artifact.experiment_id,
            strategy_id=artifact.strategy_id,
            dataset_snapshot_ids=artifact.dataset_snapshot_ids,
            params_hash=artifact.params_hash,
            code_hash=artifact.code_hash,
            seed=artifact.seed,
            metrics=artifact.metrics,
            created_at=artifact.created_at,
            status=ExperimentStatus.APPROVED,
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
            notes=artifact.notes,
        )
        self._store[experiment_id] = updated
        log.info("experiment_approved", experiment_id=experiment_id, approved_by=approved_by)
        _schedule_persist(self._persist(updated))
        return updated

    def archive(self, experiment_id: str) -> ExperimentArtifact:
        """Transition experiment to ARCHIVED (read-only reference)."""
        artifact = self._get_or_raise(experiment_id)
        updated = ExperimentArtifact(
            experiment_id=artifact.experiment_id,
            strategy_id=artifact.strategy_id,
            dataset_snapshot_ids=artifact.dataset_snapshot_ids,
            params_hash=artifact.params_hash,
            code_hash=artifact.code_hash,
            seed=artifact.seed,
            metrics=artifact.metrics,
            created_at=artifact.created_at,
            status=ExperimentStatus.ARCHIVED,
            approved_by=artifact.approved_by,
            approved_at=artifact.approved_at,
            notes=artifact.notes,
        )
        self._store[experiment_id] = updated
        log.info("experiment_archived", experiment_id=experiment_id)
        _schedule_persist(self._persist(updated))
        return updated

    def get(self, experiment_id: str) -> ExperimentArtifact | None:
        return self._store.get(experiment_id)

    def list_by_strategy(self, strategy_id: str) -> list[ExperimentArtifact]:
        return [e for e in self._store.values() if e.strategy_id == strategy_id]

    def list_approved(self) -> list[ExperimentArtifact]:
        return [e for e in self._store.values() if e.is_approved]

    def find_duplicate(self, artifact: ExperimentArtifact) -> ExperimentArtifact | None:
        """Return an existing artifact with the same fingerprint, or None."""
        for existing in self._store.values():
            if existing.fingerprint == artifact.fingerprint:
                return existing
        return None

    def _get_or_raise(self, experiment_id: str) -> ExperimentArtifact:
        artifact = self._store.get(experiment_id)
        if artifact is None:
            raise KeyError(f"Experiment '{experiment_id}' not found")
        return artifact

    def __len__(self) -> int:
        return len(self._store)

    # ── DB persistence ────────────────────────────────────────────────────────

    async def _persist(self, artifact: ExperimentArtifact) -> None:
        """Upsert artifact to Postgres experiments table."""
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:  # type: ignore[attr-defined]
                await conn.execute(
                    """
                    INSERT INTO experiments (
                        experiment_id, strategy_id, dataset_snapshot_ids,
                        params_hash, code_hash, seed, metrics,
                        status, approved_by, approved_at, notes, created_at
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                    ON CONFLICT (experiment_id) DO UPDATE SET
                        status       = EXCLUDED.status,
                        approved_by  = EXCLUDED.approved_by,
                        approved_at  = EXCLUDED.approved_at,
                        metrics      = EXCLUDED.metrics,
                        notes        = EXCLUDED.notes
                    """,
                    artifact.experiment_id,
                    artifact.strategy_id,
                    json.dumps(list(artifact.dataset_snapshot_ids)),
                    artifact.params_hash,
                    artifact.code_hash,
                    artifact.seed,
                    json.dumps(artifact.metrics),
                    str(artifact.status),
                    artifact.approved_by,
                    artifact.approved_at,
                    artifact.notes,
                    artifact.created_at,
                )
        except Exception as exc:
            log.error(
                "experiment_registry_persist_failed",
                experiment_id=artifact.experiment_id,
                error=str(exc),
            )

    async def load_from_db(self) -> int:
        """Load all experiments from Postgres into in-memory store.

        Returns the number of experiments loaded.  No-op if pool is None.
        """
        if self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:  # type: ignore[attr-defined]
                rows = await conn.fetch(
                    """
                    SELECT experiment_id, strategy_id, dataset_snapshot_ids,
                           params_hash, code_hash, seed, metrics,
                           status, approved_by, approved_at, notes, created_at
                    FROM experiments
                    ORDER BY created_at ASC
                    """
                )
        except Exception as exc:
            log.error("experiment_registry_load_failed", error=str(exc))
            return 0

        count = 0
        for row in rows:
            try:
                snapshot_ids = (
                    json.loads(row["dataset_snapshot_ids"])
                    if isinstance(row["dataset_snapshot_ids"], str)
                    else list(row["dataset_snapshot_ids"])
                )
                metrics = (
                    json.loads(row["metrics"])
                    if isinstance(row["metrics"], str)
                    else dict(row["metrics"])
                )
                artifact = ExperimentArtifact(
                    experiment_id=str(row["experiment_id"]),
                    strategy_id=row["strategy_id"],
                    dataset_snapshot_ids=tuple(sorted(snapshot_ids)),
                    params_hash=row["params_hash"],
                    code_hash=row["code_hash"],
                    seed=row["seed"],
                    metrics=metrics,
                    created_at=row["created_at"],
                    status=ExperimentStatus(row["status"]),
                    approved_by=row["approved_by"] or "",
                    approved_at=row["approved_at"],
                    notes=row["notes"] or "",
                )
                self._store[artifact.experiment_id] = artifact
                count += 1
            except Exception as exc:
                log.warning(
                    "experiment_registry_row_parse_failed",
                    experiment_id=str(row.get("experiment_id", "?")),
                    error=str(exc),
                )

        log.info("experiment_registry_loaded", count=count)
        return count


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def hash_params(params: dict[str, object]) -> str:
    """Deterministic SHA-256 of a strategy parameter dict."""
    raw = json.dumps(params, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def hash_file(path: str) -> str:
    """SHA-256 of a file's contents. Raises FileNotFoundError if missing."""
    import pathlib

    data = pathlib.Path(path).read_bytes()
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: ExperimentRegistry | None = None


def get_experiment_registry() -> ExperimentRegistry:
    global _registry
    if _registry is None:
        _registry = ExperimentRegistry()
    return _registry
