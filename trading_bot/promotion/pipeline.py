"""Strategy promotion pipeline — formal gates between trading tiers.

A strategy must pass quantitative gates before advancing to the next tier.
No strategy may skip a tier. Live trading requires full pipeline traversal.

Tiers (from PLAN.md):
    SHADOW      — computes signals only, no fills (validation)
    PAPER       — paper fills via PaperExchange
    MICRO_LIVE  — real capital, reduced size (future Stage 9)
    LIVE        — full production capital (future Stage 9)

Gate criteria are conservative by design. Tighten before live activation.
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
        failures: list[str] = []

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

    def advance(self, metrics: StrategyMetrics) -> PromotionTier | None:
        """Attempt to advance to the next tier. Returns new tier or None if blocked."""
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
    """Query paper_orders table and compute point-in-time metrics for a strategy.

    Returns None if insufficient data exists (< 5 trades).
    """
    import math
    from typing import Any

    try:
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            rows = await conn.fetch(
                """
                SELECT side, fill_price, requested_qty,
                       created_at, status
                FROM paper_orders
                WHERE strategy_id = $1
                  AND status IN ('filled', 'rejected')
                ORDER BY created_at ASC
                """,
                strategy_id,
            )
    except Exception:
        return None

    if not rows:
        return None

    filled = [r for r in rows if r["status"] == "filled"]
    total_trades = len(rows)
    if total_trades < 5:
        return None

    # days_running — elapsed since first order
    first_at: Any = rows[0]["created_at"]
    days_running = max(1, (datetime.now(UTC) - first_at).days)

    # win_rate — buy followed by sell at higher price (simplified: compare fill prices)
    wins = 0
    buys: list[tuple[float, float]] = []  # (price, qty)
    for row in filled:
        if row["side"] == "buy" and row["fill_price"]:
            buys.append((float(row["fill_price"]), float(row["requested_qty"] or 0)))
        elif row["side"] == "sell" and row["fill_price"] and buys:
            buy_price, _ = buys.pop(0)
            if float(row["fill_price"]) > buy_price:
                wins += 1

    sell_count = sum(1 for r in filled if r["side"] == "sell")
    win_rate = wins / sell_count if sell_count > 0 else 0.0

    # sharpe — approximate from daily fill price changes (simplified)
    if len(filled) >= 2:
        prices = [float(r["fill_price"]) for r in filled if r["fill_price"]]
        if len(prices) >= 2:
            returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]
            mean_r = sum(returns) / len(returns)
            variance = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            std_r = math.sqrt(variance) if variance > 0 else 0.001
            sharpe = (mean_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # max_drawdown from portfolio snapshot (use 0 if unavailable)
    from trading_bot.portfolio.manager import get_portfolio_manager

    snapshot = get_portfolio_manager().get_snapshot()
    max_drawdown = abs(float(snapshot.daily_drawdown_pct))

    return StrategyMetrics(
        days_running=days_running,
        sharpe_ratio=round(sharpe, 4),
        max_drawdown_pct=round(max_drawdown, 4),
        win_rate=round(win_rate, 4),
        total_trades=total_trades,
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
