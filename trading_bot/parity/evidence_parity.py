"""Compute a paper↔backtest parity score for the evidence store.

Gate 0 requires a parity score (paper trading vs backtest) ≥ 0.70, but nothing
computed it — WeeklyEvidenceSummary.parity_score stayed None. This module fills
that gap: for each strategy it compares the latest in-memory backtest metrics
against the paper-trading metrics derived from paper_orders, scores them with
ParityScorer, and returns the mean as a 0-1 fraction.

Only metrics reliably available from BOTH sides are scored (win_rate,
max_drawdown_pct). Drawdowns are normalised to fractions so a percent-vs-fraction
source mismatch cannot skew the score. Returns None when there is not enough data
(no backtests yet, or a strategy has < 5 paper trades).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trading_bot.backtesting.runner import get_latest_backtest
from trading_bot.observability.logging import get_logger
from trading_bot.parity.report import ParityScorer, ParityScoringConfig, StrategySnapshot
from trading_bot.promotion.pipeline import collect_strategy_metrics

log = get_logger(__name__)

# Only metrics both a backtest and paper trading reliably expose. win_rate is the
# most trustworthy (fraction on both sides); drawdown is weighted lower.
_PARITY_CONFIG = ParityScoringConfig(
    pass_threshold=70.0,
    metric_configs={
        "win_rate": (10.0, 0.7),
        "max_drawdown_pct": (15.0, 0.3),
    },
)


def _norm_drawdown(value: float) -> float:
    """Normalise a drawdown to a fraction (a source using percent gets /100)."""
    v = abs(value)
    return v / 100.0 if v > 1.0 else v


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


async def compute_parity_score(pool: object) -> Decimal | None:
    """Mean paper↔backtest parity across strategies as a 0-1 fraction, or None.

    None when no backtest results exist yet or no strategy has enough paper data.
    """
    backtests = get_latest_backtest()
    if not backtests:
        return None

    # Group backtest metrics by strategy (a strategy may run on several symbols).
    by_strategy: dict[str, list[tuple[float, float]]] = {}
    for bt in backtests:
        by_strategy.setdefault(bt.strategy_id, []).append(
            (bt.metrics.win_rate, _norm_drawdown(bt.metrics.max_drawdown_pct))
        )

    scorer = ParityScorer(_PARITY_CONFIG)
    now = datetime.now(UTC)
    scores: list[float] = []

    for strategy_id, metric_pairs in by_strategy.items():
        paper = await collect_strategy_metrics(strategy_id, pool)
        if paper is None:  # < 5 paper trades — skip
            continue

        bt_win = _mean([w for w, _ in metric_pairs])
        bt_dd = _mean([d for _, d in metric_pairs])

        bt_snap = StrategySnapshot(
            strategy_id=strategy_id,
            environment="backtest",
            period_start=now,
            period_end=now,
            win_rate=bt_win,
            max_drawdown_pct=bt_dd,
            total_trades=paper.total_trades,
        )
        paper_snap = StrategySnapshot(
            strategy_id=strategy_id,
            environment="paper",
            period_start=now,
            period_end=now,
            win_rate=paper.win_rate,
            max_drawdown_pct=_norm_drawdown(paper.max_drawdown_pct),
            total_trades=paper.total_trades,
        )
        report = scorer.compare(bt_snap, paper_snap, label=f"{strategy_id}:backtest_vs_paper")
        scores.append(report.score)
        log.info(
            "parity_strategy_scored",
            strategy_id=strategy_id,
            score=round(report.score, 1),
            bt_win_rate=round(bt_win, 4),
            paper_win_rate=round(paper.win_rate, 4),
        )

    if not scores:
        return None

    # ParityScorer produces 0-100; the evidence gate compares on a 0-1 scale.
    return Decimal(str(round(_mean(scores) / 100.0, 4)))
