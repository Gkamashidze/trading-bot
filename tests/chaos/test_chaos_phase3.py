"""Chaos Testing — Phase 3 expanded scenarios — Feature #14.

Tests system resilience under adversarial conditions:
  - Clock skew: stale timestamps accepted vs rejected
  - DB unavailable: secrets manager degrades gracefully
  - Lineage corruption: snapshot mismatch detected
  - Duplicate events: idempotent snapshot creation
  - Stale market data: old snapshot triggers RPO failure in DR drill
  - Partial data: accounting ledger handles zero-fee and zero-quantity edge cases
  - Experiment fingerprint collision: registry finds duplicates reliably
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from trading_bot.accounting.ledger import AccountingLedger
from trading_bot.data.lineage import LineageStore, SnapshotMismatchError
from trading_bot.disaster_recovery.snapshotter import (
    RPO_TARGET_MINUTES,
    StateSnapshot,
    run_restore_drill,
    save_snapshot,
)
from trading_bot.research.experiment import ExperimentRegistry
from trading_bot.secrets.manager import EnvSecretsProvider, redact
from trading_bot.tca.tracker import FillQualityScore, OrderOutcome, TCATracker

# ---------------------------------------------------------------------------
# Clock skew / stale timestamps
# ---------------------------------------------------------------------------


class TestClockSkew:
    def test_very_old_snapshot_fails_rpo(self, tmp_path: Path) -> None:
        """A snapshot 2 hours old should fail the RPO gate."""
        old_ts = datetime.now(UTC) - timedelta(hours=2)
        snap = StateSnapshot(
            captured_at=old_ts.isoformat(),
            total_equity=10_000.0,
            cash_balance=8_000.0,
            daily_pnl=0.0,
            daily_drawdown_pct=0.0,
            position_count=0,
            positions=[],
            cb_tier=0,
            cb_peak_tier=0,
            cb_tripped_at=None,
            manager_type="paper",
        )
        save_snapshot(snap, directory=tmp_path)
        result = run_restore_drill(directory=tmp_path)
        assert result.rpo_passed is False
        assert result.rpo_minutes > RPO_TARGET_MINUTES

    def test_future_snapshot_passes_rpo(self, tmp_path: Path) -> None:
        """A snapshot timestamped slightly in the future should still pass RPO."""
        future_ts = datetime.now(UTC) + timedelta(seconds=30)
        snap = StateSnapshot(
            captured_at=future_ts.isoformat(),
            total_equity=10_000.0,
            cash_balance=8_000.0,
            daily_pnl=0.0,
            daily_drawdown_pct=0.0,
            position_count=0,
            positions=[],
            cb_tier=0,
            cb_peak_tier=0,
            cb_tripped_at=None,
            manager_type="paper",
        )
        save_snapshot(snap, directory=tmp_path)
        result = run_restore_drill(directory=tmp_path)
        # Negative age → 0 minutes → well within RPO
        assert result.rpo_passed is True


# ---------------------------------------------------------------------------
# DB unavailable (secrets env fallback)
# ---------------------------------------------------------------------------


class TestDBUnavailable:
    def test_env_provider_raises_when_key_missing(self) -> None:
        """Simulates DB/vault unavailable: env provider raises KeyError for missing key."""
        provider = EnvSecretsProvider()
        with patch.dict("os.environ", {}, clear=False):
            import os

            os.environ.pop("NONEXISTENT_CHAOS_KEY", None)
            with pytest.raises(KeyError):
                provider.get("NONEXISTENT_CHAOS_KEY")

    def test_redact_never_raises(self) -> None:
        """redact() must not raise even for edge-case inputs."""
        assert redact("") == "***"
        assert redact("x") == "***"
        assert redact("x" * 1000) is not None


# ---------------------------------------------------------------------------
# Lineage / snapshot corruption
# ---------------------------------------------------------------------------


class TestLineageCorruption:
    def _make_lineage(self) -> object:
        from datetime import UTC, datetime

        from trading_bot.core.models import DataLineage

        return DataLineage(
            source="test",
            fetched_at=datetime.now(UTC),
            schema_version="1",
            row_count=100,
            checksum="abc123",
            provider="binance",
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            storage_path="/data/test.parquet",
        )

    def test_verify_snapshot_detects_mismatch(self) -> None:
        """Corrupted lineage should raise SnapshotMismatchError."""
        store = LineageStore()
        lineage = self._make_lineage()
        snapshot_id = store.create_snapshot(lineage)

        # Tamper: different checksum
        from datetime import UTC, datetime

        from trading_bot.core.models import DataLineage

        tampered = DataLineage(
            source="test",
            fetched_at=datetime.now(UTC),
            schema_version="1",
            row_count=100,
            checksum="TAMPERED",
            provider="binance",
            exchange="binance",
            symbol="BTC/USDT",
            timeframe="1h",
            storage_path="/data/test.parquet",
        )
        with pytest.raises(SnapshotMismatchError):
            store.verify_snapshot(snapshot_id, tampered)

    def test_verify_unknown_snapshot_raises_keyerror(self) -> None:
        store = LineageStore()
        lineage = self._make_lineage()
        with pytest.raises(KeyError):
            store.verify_snapshot("nonexistent_id", lineage)

    def test_duplicate_create_is_idempotent(self) -> None:
        """Registering the same lineage twice returns the same ID."""
        store = LineageStore()
        lineage = self._make_lineage()
        id1 = store.create_snapshot(lineage)
        id2 = store.create_snapshot(lineage)
        assert id1 == id2
        assert len(store) == 1


# ---------------------------------------------------------------------------
# Accounting ledger edge cases
# ---------------------------------------------------------------------------


class TestAccountingLedgerChaos:
    def test_zero_fee_buy_sell(self) -> None:
        """Zero-fee trades should not affect P&L calculation."""
        ledger = AccountingLedger()
        ledger.record_trade("BTC/USDT", "BUY", 1.0, 50_000.0, fee_usdt=0.0)
        ledger.record_trade("BTC/USDT", "SELL", 1.0, 55_000.0, fee_usdt=0.0)
        pnl = ledger.total_realized_pnl()
        assert pnl == Decimal("5000.00000000")

    def test_sell_without_buy_produces_no_realized(self) -> None:
        """Selling with no open lots should create no realized P&L entries."""
        ledger = AccountingLedger()
        ledger.record_trade("BTC/USDT", "SELL", 1.0, 55_000.0)
        assert len(ledger._realized) == 0

    def test_multiple_partial_sells_exhaust_lot(self) -> None:
        """Three partial sells of 0.33 each should exhaust a 1.0 BTC lot."""
        ledger = AccountingLedger()
        ledger.record_trade("BTC/USDT", "BUY", 1.0, 50_000.0)
        ledger.record_trade("BTC/USDT", "SELL", Decimal("0.33"), 55_000.0)
        ledger.record_trade("BTC/USDT", "SELL", Decimal("0.33"), 55_000.0)
        ledger.record_trade("BTC/USDT", "SELL", Decimal("0.34"), 55_000.0)
        assert len(ledger._realized) == 3
        # Total sold = 1.0, open exposure should be ~0
        exposure = ledger.open_exposure("BTC/USDT")
        assert exposure < Decimal("0.00000002")  # floating point tolerance

    def test_negative_pnl_recorded_correctly(self) -> None:
        """Loss trade should produce negative realized P&L."""
        ledger = AccountingLedger()
        ledger.record_trade("BTC/USDT", "BUY", 1.0, 55_000.0)
        ledger.record_trade("BTC/USDT", "SELL", 1.0, 50_000.0)
        pnl = ledger.total_realized_pnl()
        assert pnl < Decimal("0")


# ---------------------------------------------------------------------------
# TCA chaos / adversarial fills
# ---------------------------------------------------------------------------


class TestTCAChaos:
    def test_extremely_high_slippage_classified_poor(self) -> None:
        tracker = TCATracker()
        rec = tracker.record("o1", "BTC/USDT", "BUY", 50_000.0, 55_000.0, 0.01)
        assert rec.quality_score == FillQualityScore.POOR

    def test_rejected_orders_appear_in_outcome_dist(self) -> None:
        tracker = TCATracker()
        for i in range(5):
            tracker.record(
                f"rej{i}",
                "BTC/USDT",
                "BUY",
                50_000.0,
                50_000.0,
                0.01,
                outcome=OrderOutcome.REJECTED,
            )
        s = tracker.summary("BTC/USDT")
        dist = s["outcome_distribution"]
        assert dist.get("rejected") == 5

    def test_mixed_latency_summary(self) -> None:
        tracker = TCATracker()
        tracker.record("o1", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01, latency_ms=0.0)
        tracker.record("o2", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01, latency_ms=1000.0)
        s = tracker.summary("BTC/USDT")
        assert s["avg_latency_ms"] == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# Experiment registry: duplicate detection under load
# ---------------------------------------------------------------------------


class TestExperimentChaos:
    def test_fingerprint_stable_across_many_creates(self) -> None:
        reg = ExperimentRegistry()
        metrics = {"sharpe": 1.0}
        fingerprints = set()
        for _ in range(10):
            exp = reg.create("sma", ["snap1"], "ph", "ch", seed=42, metrics=metrics)
            fingerprints.add(exp.fingerprint)
        # All 10 experiments have same params → same fingerprint
        assert len(fingerprints) == 1

    def test_unique_seeds_produce_unique_fingerprints(self) -> None:
        reg = ExperimentRegistry()
        fingerprints = {
            reg.create("sma", ["s1"], "ph", "ch", seed=i, metrics={}).fingerprint for i in range(20)
        }
        assert len(fingerprints) == 20
