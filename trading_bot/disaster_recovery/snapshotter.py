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
