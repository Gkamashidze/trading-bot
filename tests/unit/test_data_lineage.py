"""Unit tests for the Data Lineage system (Feature #6)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_bot.core.models import DataLineage
from trading_bot.data.lineage import (
    LineageStore,
    SnapshotMismatchError,
    _snapshot_id,
    get_lineage_store,
)


def _lineage(
    symbol: str = "BTC/USDT",
    timeframe: str = "1h",
    row_count: int = 100,
    checksum: str = "abc123",
) -> DataLineage:
    return DataLineage(
        source="binance.fetch_ohlcv",
        fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
        row_count=row_count,
        checksum=checksum,
        provider="binance",
        exchange="BINANCE",
        symbol=symbol,
        timeframe=timeframe,
        storage_path=f"data/raw/binance/{symbol.replace('/', '_')}/{timeframe}/2024-01.parquet",
    )


class TestDataLineageModel:
    def test_new_fields_have_defaults(self) -> None:
        # Existing call-site with only required fields — must not break
        lineage = DataLineage(
            source="binance.fetch_ohlcv",
            fetched_at=datetime(2024, 1, 1, tzinfo=UTC),
            row_count=50,
        )
        assert lineage.provider == ""
        assert lineage.exchange == ""
        assert lineage.symbol == ""
        assert lineage.timeframe == ""
        assert lineage.ingestion_job_id == ""
        assert lineage.storage_path == ""
        assert lineage.dataset_snapshot_id == ""

    def test_full_lineage_fields(self) -> None:
        lin = _lineage()
        assert lin.symbol == "BTC/USDT"
        assert lin.provider == "binance"
        assert lin.timeframe == "1h"


class TestSnapshotId:
    def test_same_lineage_same_id(self) -> None:
        lin = _lineage()
        assert _snapshot_id(lin) == _snapshot_id(lin)

    def test_different_checksum_different_id(self) -> None:
        a = _lineage(checksum="abc")
        b = _lineage(checksum="xyz")
        assert _snapshot_id(a) != _snapshot_id(b)

    def test_different_symbol_different_id(self) -> None:
        a = _lineage(symbol="BTC/USDT")
        b = _lineage(symbol="ETH/USDT")
        assert _snapshot_id(a) != _snapshot_id(b)

    def test_id_is_64_char_hex(self) -> None:
        sid = _snapshot_id(_lineage())
        assert len(sid) == 64
        int(sid, 16)  # must parse as hex


class TestLineageStore:
    def setup_method(self) -> None:
        self.store = LineageStore()

    def test_create_and_retrieve(self) -> None:
        lin = _lineage()
        sid = self.store.create_snapshot(lin)
        snap = self.store.get_snapshot(sid)
        assert snap is not None
        assert snap.snapshot_id == sid
        assert snap.lineage == lin

    def test_idempotent_create(self) -> None:
        lin = _lineage()
        sid1 = self.store.create_snapshot(lin)
        sid2 = self.store.create_snapshot(lin)
        assert sid1 == sid2
        assert len(self.store) == 1

    def test_get_unknown_returns_none(self) -> None:
        assert self.store.get_snapshot("nonexistent") is None

    def test_verify_passes_for_matching(self) -> None:
        lin = _lineage()
        sid = self.store.create_snapshot(lin)
        self.store.verify_snapshot(sid, lin)  # must not raise

    def test_verify_raises_for_mismatch(self) -> None:
        lin_a = _lineage(checksum="aaa")
        lin_b = _lineage(checksum="bbb")
        sid_a = self.store.create_snapshot(lin_a)
        with pytest.raises(SnapshotMismatchError):
            self.store.verify_snapshot(sid_a, lin_b)

    def test_verify_raises_for_unknown_id(self) -> None:
        with pytest.raises(KeyError):
            self.store.verify_snapshot("unknown_id_000", _lineage())

    def test_multiple_snapshots(self) -> None:
        self.store.create_snapshot(_lineage("BTC/USDT"))
        self.store.create_snapshot(_lineage("ETH/USDT"))
        assert len(self.store) == 2
        assert len(self.store.all_snapshots()) == 2

    def test_snapshot_has_created_at(self) -> None:
        lin = _lineage()
        sid = self.store.create_snapshot(lin)
        snap = self.store.get_snapshot(sid)
        assert snap is not None
        assert snap.created_at.tzinfo is not None

    def test_backtest_cannot_use_untracked_snapshot(self) -> None:
        """A snapshot ID that was never registered should raise KeyError."""
        with pytest.raises(KeyError):
            self.store.verify_snapshot("made_up_id_12345", _lineage())


class TestLineageStoreSingleton:
    def test_get_lineage_store_returns_same_instance(self) -> None:
        s1 = get_lineage_store()
        s2 = get_lineage_store()
        assert s1 is s2
