"""Tests for Feature #10: Disaster Recovery Rehearsal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from trading_bot.disaster_recovery.snapshotter import (
    RPO_TARGET_MINUTES,
    RTO_TARGET_SECONDS,
    DrillResult,
    StateSnapshot,
    get_drill_history,
    run_restore_drill,
    save_snapshot,
)


def _snap(age_minutes: float = 0.0) -> StateSnapshot:
    ts = datetime.now(UTC) - timedelta(minutes=age_minutes)
    return StateSnapshot(
        captured_at=ts.isoformat(),
        total_equity=10_000.0,
        cash_balance=8_000.0,
        daily_pnl=50.0,
        daily_drawdown_pct=-0.005,
        position_count=1,
        positions=[],
        cb_tier=0,
        cb_peak_tier=0,
        cb_tripped_at=None,
        manager_type="paper",
    )


class TestDrillResult:
    def test_passed_when_both_targets_met(self) -> None:
        result = DrillResult(
            drill_id="d1",
            started_at=datetime.now(UTC).isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
            rto_seconds=1.0,
            rpo_minutes=30.0,
            rto_passed=True,
            rpo_passed=True,
        )
        assert result.passed is True

    def test_failed_when_rto_exceeded(self) -> None:
        result = DrillResult(
            drill_id="d2",
            started_at=datetime.now(UTC).isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
            rto_seconds=600.0,
            rpo_minutes=10.0,
            rto_passed=False,
            rpo_passed=True,
        )
        assert result.passed is False

    def test_failed_when_rpo_exceeded(self) -> None:
        result = DrillResult(
            drill_id="d3",
            started_at=datetime.now(UTC).isoformat(),
            finished_at=datetime.now(UTC).isoformat(),
            rto_seconds=1.0,
            rpo_minutes=120.0,
            rto_passed=True,
            rpo_passed=False,
        )
        assert result.passed is False


class TestRunRestoreDrill:
    def test_drill_passes_with_fresh_snapshot(self, tmp_path: Path) -> None:
        save_snapshot(_snap(age_minutes=1.0), directory=tmp_path)
        result = run_restore_drill(directory=tmp_path)
        assert result.rpo_passed is True
        assert result.rto_passed is True
        assert result.passed is True

    def test_drill_fails_rpo_with_old_snapshot(self, tmp_path: Path) -> None:
        old_snap = _snap(age_minutes=RPO_TARGET_MINUTES + 30.0)
        save_snapshot(old_snap, directory=tmp_path)
        result = run_restore_drill(directory=tmp_path)
        assert result.rpo_passed is False

    def test_drill_fails_when_no_snapshot(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = run_restore_drill(directory=empty_dir)
        assert result.passed is False
        assert "No snapshot" in result.notes

    def test_drill_returns_drill_result(self, tmp_path: Path) -> None:
        save_snapshot(_snap(), directory=tmp_path)
        result = run_restore_drill(directory=tmp_path)
        assert isinstance(result, DrillResult)
        assert result.drill_id != ""
        assert result.started_at != ""
        assert result.finished_at != ""

    def test_drill_appended_to_history(self, tmp_path: Path) -> None:
        before = len(get_drill_history())
        save_snapshot(_snap(), directory=tmp_path)
        run_restore_drill(directory=tmp_path)
        assert len(get_drill_history()) == before + 1

    def test_drill_rto_seconds_is_non_negative(self, tmp_path: Path) -> None:
        save_snapshot(_snap(), directory=tmp_path)
        result = run_restore_drill(directory=tmp_path)
        assert result.rto_seconds >= 0.0

    def test_drill_notes_all_targets_met(self, tmp_path: Path) -> None:
        save_snapshot(_snap(age_minutes=1.0), directory=tmp_path)
        result = run_restore_drill(directory=tmp_path)
        assert "All targets met" in result.notes


class TestDRTargets:
    def test_rpo_target_is_60_minutes(self) -> None:
        assert RPO_TARGET_MINUTES == 60

    def test_rto_target_is_300_seconds(self) -> None:
        assert RTO_TARGET_SECONDS == 300
