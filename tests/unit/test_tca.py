"""Tests for Stage 8 TCA Tracker."""

from __future__ import annotations

import pytest

from trading_bot.tca.tracker import FillRecord, TCATracker, get_tca_tracker


class TestFillRecord:
    def test_buy_slippage_positive_when_fill_above_signal(self) -> None:
        from datetime import UTC, datetime

        rec = FillRecord(
            order_id="o1",
            symbol="BTC/USDT",
            side="BUY",
            signal_price=50000.0,
            fill_price=50100.0,
            quantity=0.01,
            filled_at=datetime.now(UTC),
        )
        assert rec.slippage_pct == pytest.approx(0.002)  # 0.2% worse

    def test_sell_slippage_positive_when_fill_below_signal(self) -> None:
        from datetime import UTC, datetime

        rec = FillRecord(
            order_id="o2",
            symbol="BTC/USDT",
            side="SELL",
            signal_price=50000.0,
            fill_price=49900.0,
            quantity=0.01,
            filled_at=datetime.now(UTC),
        )
        assert rec.slippage_pct == pytest.approx(0.002)  # 0.2% worse

    def test_zero_slippage_on_exact_fill(self) -> None:
        from datetime import UTC, datetime

        rec = FillRecord(
            order_id="o3",
            symbol="BTC/USDT",
            side="BUY",
            signal_price=50000.0,
            fill_price=50000.0,
            quantity=1.0,
            filled_at=datetime.now(UTC),
        )
        assert rec.slippage_pct == pytest.approx(0.0)
        assert rec.slippage_usdt == pytest.approx(0.0)

    def test_slippage_usdt_calculation(self) -> None:
        from datetime import UTC, datetime

        rec = FillRecord(
            order_id="o4",
            symbol="BTC/USDT",
            side="BUY",
            signal_price=50000.0,
            fill_price=50100.0,
            quantity=0.1,
            filled_at=datetime.now(UTC),
        )
        assert rec.slippage_usdt == pytest.approx(10.0)


class TestTCATracker:
    def test_record_stores_fill(self) -> None:
        tracker = TCATracker()
        rec = tracker.record("o1", "BTC/USDT", "BUY", 50000.0, 50050.0, 0.01)
        assert rec.order_id == "o1"
        assert len(tracker._records) == 1

    def test_summary_empty(self) -> None:
        tracker = TCATracker()
        s = tracker.summary()
        assert s["count"] == 0

    def test_summary_aggregates(self) -> None:
        tracker = TCATracker()
        tracker.record("o1", "BTC/USDT", "BUY", 50000.0, 50100.0, 0.01)
        tracker.record("o2", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01)
        s = tracker.summary("BTC/USDT")
        assert s["count"] == 2
        assert s["avg_slippage_pct"] == pytest.approx(0.001)

    def test_summary_filters_by_symbol(self) -> None:
        tracker = TCATracker()
        tracker.record("o1", "BTC/USDT", "BUY", 50000.0, 50100.0, 0.01)
        tracker.record("o2", "ETH/USDT", "BUY", 3000.0, 3010.0, 0.1)
        btc_summary = tracker.summary("BTC/USDT")
        eth_summary = tracker.summary("ETH/USDT")
        assert btc_summary["count"] == 1
        assert eth_summary["count"] == 1

    def test_recent_returns_last_n(self) -> None:
        tracker = TCATracker()
        for i in range(5):
            tracker.record(f"o{i}", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01)
        recent = tracker.recent(3)
        assert len(recent) == 3

    def test_singleton_returns_same_instance(self) -> None:
        t1 = get_tca_tracker()
        t2 = get_tca_tracker()
        assert t1 is t2
