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

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


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
    """In-memory store of experiment artifacts.

    Experiments are append-only; approval/archival create updated copies.
    """

    def __init__(self) -> None:
        self._store: dict[str, ExperimentArtifact] = {}

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
