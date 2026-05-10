"""Transaction Cost Analysis — slippage and fill quality tracking.

Tracks the difference between the price at signal time and the actual
paper fill price. In paper trading, fills are simulated at signal price,
so slippage is always 0 — this establishes the baseline for comparison
when live execution is introduced.

Usage:
    tracker = get_tca_tracker()
    tracker.record(order_id="abc", symbol="BTC/USDT", side="BUY",
                   signal_price=50000.0, fill_price=50010.0, quantity=0.01)
    summary = tracker.summary("BTC/USDT")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


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
        )
        self._records.append(rec)
        log.info(
            "tca_fill_recorded",
            symbol=symbol,
            side=side,
            slippage_pct=f"{rec.slippage_pct:.4%}",
            slippage_usdt=f"{rec.slippage_usdt:.4f}",
        )
        return rec

    def summary(self, symbol: str | None = None) -> dict[str, object]:
        """Return aggregate TCA stats, optionally filtered by symbol."""
        records = [r for r in self._records if symbol is None or r.symbol == symbol]
        if not records:
            return {"count": 0, "avg_slippage_pct": 0.0, "total_slippage_usdt": 0.0}

        avg_slip = sum(r.slippage_pct for r in records) / len(records)
        total_usdt = sum(r.slippage_usdt for r in records)
        return {
            "count": len(records),
            "avg_slippage_pct": round(avg_slip, 6),
            "total_slippage_usdt": round(total_usdt, 4),
            "symbol": symbol,
        }

    def recent(self, n: int = 20) -> list[FillRecord]:
        return list(reversed(self._records[-n:]))


# ── Module-level singleton ────────────────────────────────────────────────────

_tracker: TCATracker | None = None


def get_tca_tracker() -> TCATracker:
    global _tracker
    if _tracker is None:
        _tracker = TCATracker()
    return _tracker
