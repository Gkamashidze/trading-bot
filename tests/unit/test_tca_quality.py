"""Tests for Feature #4: TCA quality extension."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trading_bot.tca.tracker import (
    FillQualityScore,
    FillRecord,
    OrderOutcome,
    TCATracker,
)


def _rec(
    slippage_frac: float = 0.0,
    side: str = "BUY",
    outcome: OrderOutcome = OrderOutcome.FILLED,
    latency_ms: float = 10.0,
    retry_count: int = 0,
    reject_reason: str = "",
) -> FillRecord:
    base = 50_000.0
    fill = base * (1 + slippage_frac)
    return FillRecord(
        order_id="o1",
        symbol="BTC/USDT",
        side=side,
        signal_price=base,
        fill_price=fill,
        quantity=0.01,
        filled_at=datetime.now(UTC),
        latency_ms=latency_ms,
        outcome=outcome,
        retry_count=retry_count,
        reject_reason=reject_reason,
    )


class TestFillQualityScore:
    def test_zero_slippage_is_excellent(self) -> None:
        rec = _rec(slippage_frac=0.0)
        assert rec.quality_score == FillQualityScore.EXCELLENT

    def test_tiny_slippage_is_excellent(self) -> None:
        rec = _rec(slippage_frac=0.0001)  # 0.01% < 0.05% threshold
        assert rec.quality_score == FillQualityScore.EXCELLENT

    def test_moderate_slippage_is_good(self) -> None:
        rec = _rec(slippage_frac=0.001)  # 0.10%
        assert rec.quality_score == FillQualityScore.GOOD

    def test_borderline_good_fair(self) -> None:
        rec = _rec(slippage_frac=0.003)  # 0.30%
        assert rec.quality_score == FillQualityScore.FAIR

    def test_high_slippage_is_poor(self) -> None:
        rec = _rec(slippage_frac=0.01)  # 1.0%
        assert rec.quality_score == FillQualityScore.POOR

    def test_sell_quality_uses_absolute_slippage(self) -> None:
        # SELL with fill below signal = positive slippage_pct via formula
        rec = _rec(slippage_frac=-0.001, side="SELL")  # 0.10% worse for sell
        assert rec.quality_score == FillQualityScore.GOOD


class TestOrderOutcome:
    def test_default_outcome_is_filled(self) -> None:
        rec = _rec()
        assert rec.outcome == OrderOutcome.FILLED

    def test_rejected_outcome(self) -> None:
        rec = _rec(outcome=OrderOutcome.REJECTED, reject_reason="INSUFFICIENT_MARGIN")
        assert rec.outcome == OrderOutcome.REJECTED
        assert rec.reject_reason == "INSUFFICIENT_MARGIN"

    def test_canceled_outcome(self) -> None:
        rec = _rec(outcome=OrderOutcome.CANCELED)
        assert rec.outcome == OrderOutcome.CANCELED

    def test_partial_outcome(self) -> None:
        rec = _rec(outcome=OrderOutcome.PARTIAL)
        assert rec.outcome == OrderOutcome.PARTIAL

    def test_retry_count_stored(self) -> None:
        rec = _rec(retry_count=3)
        assert rec.retry_count == 3


class TestLatencyTracking:
    def test_latency_stored_in_record(self) -> None:
        rec = _rec(latency_ms=123.5)
        assert rec.latency_ms == pytest.approx(123.5)

    def test_zero_latency_default(self) -> None:
        rec = _rec(latency_ms=0.0)
        assert rec.latency_ms == pytest.approx(0.0)


class TestTCATrackerExtended:
    def test_record_stores_outcome(self) -> None:
        tracker = TCATracker()
        rec = tracker.record(
            "o1",
            "BTC/USDT",
            "BUY",
            50000.0,
            50000.0,
            0.01,
            outcome=OrderOutcome.REJECTED,
            reject_reason="NO_FUNDS",
        )
        assert rec.outcome == OrderOutcome.REJECTED
        assert rec.reject_reason == "NO_FUNDS"

    def test_summary_includes_avg_latency(self) -> None:
        tracker = TCATracker()
        tracker.record("o1", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01, latency_ms=100.0)
        tracker.record("o2", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01, latency_ms=200.0)
        s = tracker.summary("BTC/USDT")
        assert s["avg_latency_ms"] == pytest.approx(150.0)

    def test_summary_includes_quality_distribution(self) -> None:
        tracker = TCATracker()
        tracker.record("o1", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01)  # excellent
        tracker.record("o2", "BTC/USDT", "BUY", 50000.0, 50500.0, 0.01)  # poor
        s = tracker.summary("BTC/USDT")
        dist = s["quality_distribution"]
        assert isinstance(dist, dict)
        assert "excellent" in dist
        assert "poor" in dist

    def test_summary_includes_outcome_distribution(self) -> None:
        tracker = TCATracker()
        tracker.record("o1", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01, outcome=OrderOutcome.FILLED)
        tracker.record(
            "o2", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01, outcome=OrderOutcome.REJECTED
        )
        s = tracker.summary("BTC/USDT")
        dist = s["outcome_distribution"]
        assert dist.get("filled") == 1
        assert dist.get("rejected") == 1

    def test_quality_filter_returns_matching_records(self) -> None:
        tracker = TCATracker()
        tracker.record("o1", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01)  # excellent
        tracker.record("o2", "BTC/USDT", "BUY", 50000.0, 50600.0, 0.01)  # poor
        excellent = tracker.quality_filter(FillQualityScore.EXCELLENT)
        poor = tracker.quality_filter(FillQualityScore.POOR)
        assert len(excellent) == 1
        assert len(poor) == 1

    def test_quality_filter_symbol_scoped(self) -> None:
        tracker = TCATracker()
        tracker.record("o1", "BTC/USDT", "BUY", 50000.0, 50000.0, 0.01)
        tracker.record("o2", "ETH/USDT", "BUY", 3000.0, 3000.0, 0.1)
        btc_excellent = tracker.quality_filter(FillQualityScore.EXCELLENT, symbol="BTC/USDT")
        assert len(btc_excellent) == 1
        assert btc_excellent[0].symbol == "BTC/USDT"

    def test_empty_summary_has_all_keys(self) -> None:
        tracker = TCATracker()
        s = tracker.summary()
        assert "avg_latency_ms" in s
        assert "quality_distribution" in s
        assert "outcome_distribution" in s
