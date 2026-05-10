"""Portfolio state snapshotter — hourly backups for disaster recovery.

Snapshots write to /data/snapshots/ (Railway persistent volume or local /tmp/snapshots).
Each file: state_YYYYMMDD_HHMMSS.json.

RPO: 1 hour (snapshot interval = job frequency).
RTO: < 5 minutes (read latest + warm-start bot).

Restore procedure (runbook): see trading_bot/docs/runbooks/disaster-recovery.md
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_DEFAULT_SNAPSHOT_DIR = Path("/data/snapshots")
_FILENAME_PREFIX = "state_"
_KEEP_LAST = 168  # 7 days x 24 h = 168 hourly snapshots


@dataclass
class StateSnapshot:
    captured_at: str  # ISO-8601 UTC string — safe for JSON roundtrip
    total_equity: float
    cash_balance: float
    daily_pnl: float
    daily_drawdown_pct: float
    position_count: int
    positions: list[dict[str, object]]  # [{symbol, qty, avg_cost, current_price}]
    cb_tier: int
    cb_peak_tier: int
    cb_tripped_at: str | None
    manager_type: str  # "paper" or future "live"


def capture_snapshot() -> StateSnapshot:
    """Read current live state from portfolio manager + circuit breaker."""
    from trading_bot.portfolio.manager import get_portfolio_manager
    from trading_bot.safety.circuit_breaker import get_circuit_breaker

    portfolio = get_portfolio_manager()
    cb = get_circuit_breaker()
    snap = portfolio.get_snapshot()

    positions = [
        {
            "symbol": p.symbol,
            "qty": float(p.quantity),
            "avg_cost": float(p.average_cost),
            "current_price": float(p.current_price),
        }
        for p in snap.positions
    ]

    return StateSnapshot(
        captured_at=datetime.now(UTC).isoformat(),
        total_equity=float(snap.total_equity),
        cash_balance=float(snap.cash_balance),
        daily_pnl=float(snap.daily_pnl),
        daily_drawdown_pct=float(snap.daily_drawdown_pct),
        position_count=len(positions),
        positions=positions,
        cb_tier=cb.current_tier,
        cb_peak_tier=cb.peak_tier_today,
        cb_tripped_at=cb.tripped_at.isoformat() if cb.tripped_at else None,
        manager_type="paper",
    )


def save_snapshot(
    snapshot: StateSnapshot,
    directory: Path = _DEFAULT_SNAPSHOT_DIR,
) -> Path:
    """Serialize snapshot to JSON. Returns the written file path."""
    directory.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    path = directory / f"{_FILENAME_PREFIX}{ts}.json"
    path.write_text(json.dumps(asdict(snapshot), indent=2))
    log.info(
        "snapshot_saved",
        path=str(path),
        total_equity=snapshot.total_equity,
        cb_tier=snapshot.cb_tier,
    )
    return path


def restore_latest_snapshot(
    directory: Path = _DEFAULT_SNAPSHOT_DIR,
) -> StateSnapshot | None:
    """Return the most recent snapshot from disk, or None if none exist."""
    if not directory.exists():
        log.warning("snapshot_directory_missing", path=str(directory))
        return None

    files = sorted(directory.glob(f"{_FILENAME_PREFIX}*.json"), reverse=True)
    if not files:
        log.info("no_snapshots_found", directory=str(directory))
        return None

    latest = files[0]
    try:
        data = json.loads(latest.read_text())
        snap = StateSnapshot(**data)
        log.info("snapshot_restored", path=str(latest), captured_at=snap.captured_at)
        return snap
    except Exception as e:
        log.error("snapshot_restore_failed", path=str(latest), error=str(e))
        return None


def prune_old_snapshots(
    directory: Path = _DEFAULT_SNAPSHOT_DIR,
    keep_last: int = _KEEP_LAST,
) -> int:
    """Delete snapshots beyond `keep_last`. Returns count of files removed."""
    if not directory.exists():
        return 0
    files = sorted(directory.glob(f"{_FILENAME_PREFIX}*.json"), reverse=True)
    to_delete = files[keep_last:]
    for f in to_delete:
        f.unlink()
    if to_delete:
        log.info("snapshots_pruned", removed=len(to_delete), kept=keep_last)
    return len(to_delete)


# ---------------------------------------------------------------------------
# Disaster Recovery Rehearsal — Feature #10
# ---------------------------------------------------------------------------

import time  # noqa: E402
import uuid  # noqa: E402

# RPO/RTO targets
RPO_TARGET_MINUTES: int = 60  # max data age we tolerate on recovery
RTO_TARGET_SECONDS: int = 300  # max time to restore from snapshot


@dataclass
class DrillResult:
    """Result of a single restore-drill run."""

    drill_id: str
    started_at: str  # ISO-8601 UTC
    finished_at: str  # ISO-8601 UTC
    rto_seconds: float  # measured restore time
    rpo_minutes: float  # age of the restored snapshot in minutes
    rto_passed: bool
    rpo_passed: bool
    notes: str = ""

    @property
    def passed(self) -> bool:
        return self.rto_passed and self.rpo_passed


_drill_history: list[DrillResult] = []


def run_restore_drill(
    directory: Path = _DEFAULT_SNAPSHOT_DIR,
) -> DrillResult:
    """Execute a restore drill: measure RTO and validate RPO against targets.

    Does NOT modify live state — it only reads the snapshot from disk.
    """
    drill_id = str(uuid.uuid4())
    start_ts = datetime.now(UTC)
    t0 = time.monotonic()

    snap = restore_latest_snapshot(directory=directory)

    elapsed = time.monotonic() - t0
    end_ts = datetime.now(UTC)

    if snap is None:
        result = DrillResult(
            drill_id=drill_id,
            started_at=start_ts.isoformat(),
            finished_at=end_ts.isoformat(),
            rto_seconds=elapsed,
            rpo_minutes=float("inf"),
            rto_passed=False,
            rpo_passed=False,
            notes="No snapshot found in directory",
        )
        _drill_history.append(result)
        log.warning("dr_drill_no_snapshot", drill_id=drill_id, directory=str(directory))
        return result

    # Calculate how old the snapshot is
    captured_at = datetime.fromisoformat(snap.captured_at)
    age_minutes = (end_ts - captured_at).total_seconds() / 60.0

    rto_passed = elapsed <= RTO_TARGET_SECONDS
    rpo_passed = age_minutes <= RPO_TARGET_MINUTES

    notes = []
    if not rto_passed:
        notes.append(f"RTO exceeded: {elapsed:.1f}s > {RTO_TARGET_SECONDS}s target")
    if not rpo_passed:
        notes.append(f"RPO exceeded: {age_minutes:.1f}min > {RPO_TARGET_MINUTES}min target")

    result = DrillResult(
        drill_id=drill_id,
        started_at=start_ts.isoformat(),
        finished_at=end_ts.isoformat(),
        rto_seconds=round(elapsed, 3),
        rpo_minutes=round(age_minutes, 2),
        rto_passed=rto_passed,
        rpo_passed=rpo_passed,
        notes="; ".join(notes) if notes else "All targets met",
    )
    _drill_history.append(result)
    log.info(
        "dr_drill_complete",
        drill_id=drill_id,
        passed=result.passed,
        rto_seconds=result.rto_seconds,
        rpo_minutes=result.rpo_minutes,
    )
    return result


def get_drill_history() -> list[DrillResult]:
    return list(_drill_history)
