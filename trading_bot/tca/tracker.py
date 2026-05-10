"""Transaction Cost Analysis — slippage, fill quality, and execution scoring.

Tracks the difference between the price at signal time and the actual
paper fill price. In paper trading, fills are simulated at signal price,
so slippage is always 0 — this establishes the baseline for comparison
when live execution is introduced.

Feature #4 extension: adds FillQualityScore, OrderOutcome, latency tracking,
and retry policy classification on top of the base slippage measurement.

Usage:
    tracker = get_tca_tracker()
    tracker.record(order_id="abc", symbol="BTC/USDT", side="BUY",
                   signal_price=50000.0, fill_price=50010.0, quantity=0.01,
                   latency_ms=45.0, outcome=OrderOutcome.FILLED)
    summary = tracker.summary("BTC/USDT")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

_EXCELLENT_THRESHOLD = 0.0005  # < 0.05%
_GOOD_THRESHOLD = 0.002  # < 0.20%
_FAIR_THRESHOLD = 0.005  # < 0.50%

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FillQualityScore(StrEnum):
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"


class OrderOutcome(StrEnum):
    FILLED = "filled"
    PARTIAL = "partial"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FillRecord:
    """Single trade fill quality measurement."""

    order_id: str
    symbol: str
    side: str
    signal_price: float
    fill_price: float
    quantity: float
    filled_at: datetime
    latency_ms: float = 0.0
    outcome: OrderOutcome = OrderOutcome.FILLED
    retry_count: int = 0
    reject_reason: str = ""

    @property
    def slippage_pct(self) -> float:
        """Signed slippage: positive = filled worse than signal price."""
        if self.signal_price == 0:
            return 0.0
        raw = (self.fill_price - self.signal_price) / self.signal_price
        return raw if self.side == "BUY" else -raw

    @property
    def slippage_usdt(self) -> float:
        return abs(self.fill_price - self.signal_price) * self.quantity

    @property
    def quality_score(self) -> FillQualityScore:
        """Classify fill quality based on absolute slippage magnitude."""
        abs_slip = abs(self.slippage_pct)
        if abs_slip < _EXCELLENT_THRESHOLD:
            return FillQualityScore.EXCELLENT
        if abs_slip < _GOOD_THRESHOLD:
            return FillQualityScore.GOOD
        if abs_slip < _FAIR_THRESHOLD:
            return FillQualityScore.FAIR
        return FillQualityScore.POOR


@dataclass
class TCATracker:
    """In-memory store of fill quality records for all paper trades."""

    _records: list[FillRecord] = field(default_factory=list)

    def record(
        self,
        order_id: str,
        symbol: str,
        side: str,
        signal_price: float,
        fill_price: float,
        quantity: float,
        latency_ms: float = 0.0,
        outcome: OrderOutcome = OrderOutcome.FILLED,
        retry_count: int = 0,
        reject_reason: str = "",
    ) -> FillRecord:
        """Record a new fill and return the FillRecord."""
        rec = FillRecord(
            order_id=order_id,
            symbol=symbol,
            side=side,
            signal_price=signal_price,
            fill_price=fill_price,
            quantity=quantity,
            filled_at=datetime.now(UTC),
            latency_ms=latency_ms,
            outcome=outcome,
            retry_count=retry_count,
            reject_reason=reject_reason,
        )
        self._records.append(rec)
        log.info(
            "tca_fill_recorded",
            symbol=symbol,
            side=side,
            slippage_pct=f"{rec.slippage_pct:.4%}",
            slippage_usdt=f"{rec.slippage_usdt:.4f}",
            quality=rec.quality_score,
            latency_ms=latency_ms,
            outcome=outcome,
            retry_count=retry_count,
        )
        return rec

    def summary(self, symbol: str | None = None) -> dict[str, object]:
        """Return aggregate TCA stats, optionally filtered by symbol."""
        records = [r for r in self._records if symbol is None or r.symbol == symbol]
        if not records:
            return {
                "count": 0,
                "avg_slippage_pct": 0.0,
                "total_slippage_usdt": 0.0,
                "avg_latency_ms": 0.0,
                "quality_distribution": {},
                "outcome_distribution": {},
            }

        avg_slip = sum(r.slippage_pct for r in records) / len(records)
        total_usdt = sum(r.slippage_usdt for r in records)
        avg_latency = sum(r.latency_ms for r in records) / len(records)

        quality_dist: dict[str, int] = {}
        for r in records:
            key = str(r.quality_score)
            quality_dist[key] = quality_dist.get(key, 0) + 1

        outcome_dist: dict[str, int] = {}
        for r in records:
            key = str(r.outcome)
            outcome_dist[key] = outcome_dist.get(key, 0) + 1

        return {
            "count": len(records),
            "avg_slippage_pct": round(avg_slip, 6),
            "total_slippage_usdt": round(total_usdt, 4),
            "avg_latency_ms": round(avg_latency, 2),
            "quality_distribution": quality_dist,
            "outcome_distribution": outcome_dist,
            "symbol": symbol,
        }

    def quality_filter(
        self,
        score: FillQualityScore,
        symbol: str | None = None,
    ) -> list[FillRecord]:
        """Return fills matching the given quality score."""
        return [
            r
            for r in self._records
            if r.quality_score == score and (symbol is None or r.symbol == symbol)
        ]

    def recent(self, n: int = 20) -> list[FillRecord]:
        return list(reversed(self._records[-n:]))


# ── Module-level singleton ────────────────────────────────────────────────────

_tracker: TCATracker | None = None


def get_tca_tracker() -> TCATracker:
    global _tracker
    if _tracker is None:
        _tracker = TCATracker()
    return _tracker
