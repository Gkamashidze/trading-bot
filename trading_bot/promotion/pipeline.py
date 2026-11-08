"""Strategy promotion pipeline — formal gates between trading tiers.

A strategy must pass quantitative gates before advancing to the next tier.
No strategy may skip a tier. Live trading requires full pipeline traversal.

Tiers (from PLAN.md):
    SHADOW      — computes signals only, no fills (validation)
    PAPER       — paper fills via PaperExchange
    MICRO_LIVE  — real capital, reduced size (future Stage 9)
    LIVE        — full production capital (future Stage 9)

Gate criteria are conservative by design. Tighten before live activation.

Registry gate:
    Before advancing to any tier, the strategy must have a valid entry in the
    StrategyRegistry (approved and not expired).  This ensures every promoted
    strategy has documented provenance and owner sign-off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class PromotionTier(StrEnum):
    SHADOW = "shadow"
    PAPER = "paper"
    MICRO_LIVE = "micro_live"
    LIVE = "live"


_TIER_ORDER = [
    PromotionTier.SHADOW,
    PromotionTier.PAPER,
    PromotionTier.MICRO_LIVE,
    PromotionTier.LIVE,
]


@dataclass(frozen=True)
class PromotionGate:
    """Minimum criteria a strategy must meet to advance to the next tier."""

    tier: PromotionTier
    min_days: int
    min_sharpe: float
    max_drawdown_pct: float  # absolute value, e.g. 0.10 = 10%
    min_win_rate: float  # fraction, e.g. 0.45 = 45%
    min_trades: int


PROMOTION_GATES: dict[PromotionTier, PromotionGate] = {
    PromotionTier.SHADOW: PromotionGate(
        tier=PromotionTier.SHADOW,
        min_days=7,
        min_sharpe=0.5,
        max_drawdown_pct=0.20,
        min_win_rate=0.40,
        min_trades=10,
    ),
    PromotionTier.PAPER: PromotionGate(
        tier=PromotionTier.PAPER,
        min_days=30,
        min_sharpe=0.8,
        max_drawdown_pct=0.15,
        min_win_rate=0.45,
        min_trades=20,
    ),
    PromotionTier.MICRO_LIVE: PromotionGate(
        tier=PromotionTier.MICRO_LIVE,
        min_days=90,
        min_sharpe=1.0,
        max_drawdown_pct=0.10,
        min_win_rate=0.50,
        min_trades=50,
    ),
}


@dataclass
class StrategyMetrics:
    """Point-in-time performance metrics for a strategy."""

    days_running: int
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate: float
    total_trades: int
    evidence_errors: list[str] = field(default_factory=list)

    @property
    def evidence_complete(self) -> bool:
        return not self.evidence_errors


@dataclass
class StrategyPromotion:
    """Tracks a strategy's current promotion tier and gate evaluation."""

    strategy_id: str
    current_tier: PromotionTier = PromotionTier.SHADOW
    promoted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    history: list[tuple[PromotionTier, datetime]] = field(default_factory=list)

    def can_advance(self, metrics: StrategyMetrics) -> tuple[bool, list[str]]:
        """Check whether metrics satisfy the current tier's gate.

        Returns (eligible, reasons_for_failure).
        Always returns (False, [...]) at LIVE tier — no advancement possible.
        """
        if self.current_tier == PromotionTier.LIVE:
            return False, ["already at LIVE tier"]

        gate = PROMOTION_GATES[self.current_tier]
        import math

        failures: list[str] = list(metrics.evidence_errors)
        if not all(
            math.isfinite(v)
            for v in (metrics.sharpe_ratio, metrics.max_drawdown_pct, metrics.win_rate)
        ):
            return False, ["non-finite performance metrics"]
        if not 0 <= metrics.win_rate <= 1 or not 0 <= metrics.max_drawdown_pct <= 1:
            return False, ["performance metrics must use fractions in [0, 1]"]

        if metrics.days_running < gate.min_days:
            failures.append(f"days {metrics.days_running} < {gate.min_days} required")
        if metrics.sharpe_ratio < gate.min_sharpe:
            failures.append(f"sharpe {metrics.sharpe_ratio:.2f} < {gate.min_sharpe:.2f} required")
        if metrics.max_drawdown_pct > gate.max_drawdown_pct:
            failures.append(
                f"drawdown {metrics.max_drawdown_pct:.1%} > {gate.max_drawdown_pct:.1%} limit"
            )
        if metrics.win_rate < gate.min_win_rate:
            failures.append(f"win_rate {metrics.win_rate:.1%} < {gate.min_win_rate:.1%} required")
        if metrics.total_trades < gate.min_trades:
            failures.append(f"trades {metrics.total_trades} < {gate.min_trades} required")

        return len(failures) == 0, failures

    def advance(
        self,
        metrics: StrategyMetrics,
        require_registry: bool = True,
    ) -> PromotionTier | None:
        """Attempt to advance to the next tier. Returns new tier or None if blocked.

        If require_registry is True (default), raises RegistryError when the
        strategy has no valid entry in the governance registry.
        """
        if require_registry:
            from trading_bot.strategies.registry import get_strategy_registry

            get_strategy_registry().require_valid_entry(self.strategy_id)

        eligible, _ = self.can_advance(metrics)
        if not eligible:
            return None

        idx = _TIER_ORDER.index(self.current_tier)
        if idx + 1 >= len(_TIER_ORDER):
            return None

        next_tier = _TIER_ORDER[idx + 1]
        self.history.append((self.current_tier, datetime.now(UTC)))
        self.current_tier = next_tier
        self.promoted_at = datetime.now(UTC)
        return next_tier

    @property
    def next_gate(self) -> PromotionGate | None:
        """The gate criteria that must be met to leave the current tier."""
        return PROMOTION_GATES.get(self.current_tier)


# Module-level registry — strategies register themselves on startup.
_registry: dict[str, StrategyPromotion] = {}


def register_strategy(strategy_id: str, tier: PromotionTier = PromotionTier.SHADOW) -> None:
    """Register a strategy with an initial promotion tier."""
    if strategy_id not in _registry:
        _registry[strategy_id] = StrategyPromotion(strategy_id=strategy_id, current_tier=tier)


def get_promotion(strategy_id: str) -> StrategyPromotion | None:
    return _registry.get(strategy_id)


def get_all_promotions() -> list[StrategyPromotion]:
    return list(_registry.values())


async def collect_strategy_metrics(strategy_id: str, pool: object) -> StrategyMetrics | None:
    """Use actual net exits and recorded marked equity, never fill-price changes.

    Only observations since marked strategy evidence began count toward promotion.
    Older fills remain in the immutable evidence store, but cannot stand in for
    missing historical equity marks. Rejected submissions are not trades.
    """
    import json
    import math
    import statistics
    from typing import Any

    from trading_bot.evidence import get_current_session_id
    from trading_bot.evidence.performance import STRATEGY_EQUITY_KEY

    session_id = get_current_session_id()
    if session_id is None:
        return None
    try:
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            trades = await conn.fetch(
                """SELECT a.realized_pnl, a.captured_at
                   FROM evidence_accounting_records a
                   JOIN evidence_tca_records t
                     ON a.session_id = t.session_id AND a.order_id = t.order_id
                   WHERE a.session_id = $1 AND t.strategy_id = $2
                     AND a.side = 'sell' AND a.realized_pnl IS NOT NULL
                   ORDER BY a.captured_at""",
                session_id,
                strategy_id,
            )
            snapshots = await conn.fetch(
                """SELECT captured_at, positions FROM evidence_portfolio_snapshots
                   WHERE session_id = $1 ORDER BY captured_at, snapshot_id""",
                session_id,
            )
    except Exception:
        return None

    errors: list[str] = []
    marks: list[tuple[datetime, float]] = []
    daily: dict[Any, float] = {}
    initial = 0.0
    for row in snapshots:
        positions = row["positions"]
        if isinstance(positions, str):
            positions = json.loads(positions)
        book = positions.get(STRATEGY_EQUITY_KEY, {}).get(strategy_id)
        if book is None:
            continue
        if not book.get("complete"):
            errors.extend(book.get("errors") or ["incomplete marked equity"])
            continue
        equity, capital = float(book["equity"]), float(book["initial_capital"])
        if not all(math.isfinite(v) and v > 0 for v in (equity, capital)):
            errors.append("invalid marked equity")
            continue
        if initial and capital != initial:
            errors.append("strategy capital changed within evidence period")
        initial = capital
        at = row["captured_at"]
        if marks and (at - marks[-1][0]).total_seconds() > 25 * 3600:
            errors.append("gap in marked equity evidence exceeds 25 hours")
        marks.append((at, equity))
        if at.date() < datetime.now(UTC).date():
            daily[at.date()] = equity

    if len(daily) < 2:
        errors.append("at least two closed days of marked strategy equity are required")
    if marks and (datetime.now(UTC) - marks[-1][0]).total_seconds() > 25 * 3600:
        errors.append("marked strategy equity is stale")
    start = marks[0][0] if marks else datetime.now(UTC)
    completed = [r for r in trades if r["captured_at"] >= start]
    wins = sum(float(r["realized_pnl"]) > 0 for r in completed)
    returns: list[float] = []
    previous = initial
    for equity in daily.values():
        if previous > 0:
            returns.append(equity / previous - 1)
        previous = equity
    std = statistics.pstdev(returns) if returns else 0.0
    sharpe = statistics.mean(returns) / std * math.sqrt(365) if std > 0 else 0.0
    peak, max_dd = initial, 0.0
    for _, equity in marks:
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return StrategyMetrics(
        days_running=len(daily),
        sharpe_ratio=sharpe,
        max_drawdown_pct=max_dd,
        win_rate=wins / len(completed) if completed else 0.0,
        total_trades=len(completed),
        evidence_errors=sorted(set(errors)),
    )


async def evaluate_promotion_gates(pool: object) -> None:
    """Evaluate each registered strategy's promotion gate and log results.

    Does NOT auto-promote — operator must confirm advancement via Telegram command.
    Runs as a daily scheduler job.
    """
    from trading_bot.observability.logging import get_logger

    log = get_logger(__name__)

    for strategy_id, promotion in _registry.items():
        metrics = await collect_strategy_metrics(strategy_id, pool)
        if metrics is None:
            log.info(
                "promotion_gate_skipped",
                strategy=strategy_id,
                reason="insufficient_data",
            )
            continue

        eligible, failures = promotion.can_advance(metrics)
        log.info(
            "promotion_gate_evaluated",
            strategy=strategy_id,
            current_tier=promotion.current_tier,
            eligible=eligible,
            failures=failures,
            days_running=metrics.days_running,
            sharpe=metrics.sharpe_ratio,
            win_rate=metrics.win_rate,
            total_trades=metrics.total_trades,
        )
