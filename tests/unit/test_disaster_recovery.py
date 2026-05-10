"""Tests for Stage 7 Disaster Recovery: StateSnapshot save/restore."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trading_bot.disaster_recovery.snapshotter import (
    StateSnapshot,
    capture_snapshot,
    prune_old_snapshots,
    restore_latest_snapshot,
    save_snapshot,
)


def _make_snapshot(equity: float = 10_000.0, tier: int = 0) -> StateSnapshot:
    return StateSnapshot(
        captured_at=datetime.now(UTC).isoformat(),
        total_equity=equity,
        cash_balance=equity * 0.8,
        daily_pnl=100.0,
        daily_drawdown_pct=-0.01,
        position_count=1,
        positions=[
            {"symbol": "BTC/USDT", "qty": 0.01, "avg_cost": 50000.0, "current_price": 51000.0}
        ],
        cb_tier=tier,
        cb_peak_tier=tier,
        cb_tripped_at=None,
        manager_type="paper",
    )


def _make_portfolio_mock(equity: float = 10_000.0) -> MagicMock:
    snap = MagicMock()
    snap.total_equity = Decimal(str(equity))
    snap.cash_balance = Decimal(str(equity * 0.8))
    snap.daily_pnl = Decimal("100")
    snap.daily_drawdown_pct = Decimal("-0.01")
    pos = MagicMock()
    pos.symbol = "BTC/USDT"
    pos.quantity = Decimal("0.01")
    pos.average_cost = Decimal("50000")
    pos.current_price = Decimal("51000")
    snap.positions = [pos]
    pm = MagicMock()
    pm.get_snapshot.return_value = snap
    return pm


def _make_cb_mock(tier: int = 0) -> MagicMock:
    cb = MagicMock()
    cb.current_tier = tier
    cb.peak_tier_today = tier
    cb.tripped_at = None
    return cb


class TestSaveAndRestore:
    def test_save_creates_file(self, tmp_path: Path) -> None:
        snap = _make_snapshot()
        path = save_snapshot(snap, directory=tmp_path)
        assert path.exists()
        assert path.suffix == ".json"

    def test_save_content_is_valid_json(self, tmp_path: Path) -> None:
        snap = _make_snapshot(equity=12_345.67)
        path = save_snapshot(snap, directory=tmp_path)
        data = json.loads(path.read_text())
        assert data["total_equity"] == pytest.approx(12_345.67)

    def test_restore_latest_returns_most_recent(self, tmp_path: Path) -> None:
        snap1 = _make_snapshot(equity=9_000.0)
        snap2 = _make_snapshot(equity=10_500.0)
        save_snapshot(snap1, directory=tmp_path)
        save_snapshot(snap2, directory=tmp_path)
        restored = restore_latest_snapshot(directory=tmp_path)
        assert restored is not None
        assert restored.total_equity == pytest.approx(10_500.0)

    def test_restore_roundtrip(self, tmp_path: Path) -> None:
        original = _make_snapshot(equity=8_888.0, tier=2)
        save_snapshot(original, directory=tmp_path)
        restored = restore_latest_snapshot(directory=tmp_path)
        assert restored is not None
        assert restored.cb_tier == 2
        assert restored.manager_type == "paper"
        assert restored.position_count == 1

    def test_restore_returns_none_when_no_directory(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        result = restore_latest_snapshot(directory=missing)
        assert result is None

    def test_restore_returns_none_when_empty_directory(self, tmp_path: Path) -> None:
        result = restore_latest_snapshot(directory=tmp_path)
        assert result is None

    def test_save_creates_directory_if_missing(self, tmp_path: Path) -> None:
        nested = tmp_path / "snapshots" / "sub"
        snap = _make_snapshot()
        path = save_snapshot(snap, directory=nested)
        assert path.exists()


class TestPruneOldSnapshots:
    def test_prune_removes_excess(self, tmp_path: Path) -> None:
        for _i in range(5):
            save_snapshot(_make_snapshot(), directory=tmp_path)
        removed = prune_old_snapshots(directory=tmp_path, keep_last=3)
        assert removed == 2
        remaining = list(tmp_path.glob("state_*.json"))
        assert len(remaining) == 3

    def test_prune_noop_when_within_limit(self, tmp_path: Path) -> None:
        save_snapshot(_make_snapshot(), directory=tmp_path)
        removed = prune_old_snapshots(directory=tmp_path, keep_last=5)
        assert removed == 0

    def test_prune_noop_when_directory_missing(self, tmp_path: Path) -> None:
        removed = prune_old_snapshots(directory=tmp_path / "missing", keep_last=3)
        assert removed == 0


class TestCaptureSnapshot:
    def test_capture_reads_portfolio_and_cb(self) -> None:
        pm = _make_portfolio_mock(equity=11_000.0)
        cb = _make_cb_mock(tier=1)
        with (
            patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm),
            patch("trading_bot.safety.circuit_breaker.get_circuit_breaker", return_value=cb),
        ):
            snap = capture_snapshot()

        assert snap.total_equity == pytest.approx(11_000.0)
        assert snap.cb_tier == 1
        assert snap.position_count == 1
        assert snap.manager_type == "paper"

    def test_capture_cb_tripped_at_none(self) -> None:
        pm = _make_portfolio_mock()
        cb = _make_cb_mock(tier=0)
        cb.tripped_at = None
        with (
            patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm),
            patch("trading_bot.safety.circuit_breaker.get_circuit_breaker", return_value=cb),
        ):
            snap = capture_snapshot()

        assert snap.cb_tripped_at is None

    def test_capture_cb_tripped_at_serialized(self) -> None:
        pm = _make_portfolio_mock()
        cb = _make_cb_mock(tier=2)
        cb.tripped_at = datetime(2025, 1, 15, 10, 30, 0, tzinfo=UTC)
        with (
            patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm),
            patch("trading_bot.safety.circuit_breaker.get_circuit_breaker", return_value=cb),
        ):
            snap = capture_snapshot()

        assert snap.cb_tripped_at is not None
        assert "2025-01-15" in snap.cb_tripped_at
