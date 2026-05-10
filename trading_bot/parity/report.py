"""Paper/Live Parity Report — #2 of the production readiness roadmap.

Compares two execution environments (backtest vs paper, paper vs live) across
key metrics and produces a parity score [0-100]. Micro-live promotion requires
a passing score (default threshold: 70).

Usage:
    bt = StrategySnapshot(...)   # backtest metrics
    paper = StrategySnapshot(...)  # paper metrics
    report = ParityScorer().compare(baseline=bt, target=paper, label="backtest_vs_paper")
    if report.score < 70:
        raise PromotionBlockedError(f"parity score {report.score} < 70")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


@dataclass
class StrategySnapshot:
    """Performance metrics for a single execution environment."""

    strategy_id: str
    environment: str  # "backtest" | "paper" | "shadow" | "micro_live" | "live"
    period_start: datetime
    period_end: datetime

    # Trade-level metrics
    total_trades: int = 0
    filled_trades: int = 0
    partially_filled_trades: int = 0
    rejected_trades: int = 0

    # PnL
    gross_pnl: Decimal = Decimal("0")
    net_pnl: Decimal = Decimal("0")
    total_fees: Decimal = Decimal("0")

    # Risk/return
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float | None = None
    avg_trade_pnl: Decimal = Decimal("0")

    # Execution quality
    avg_slippage_bps: float = 0.0
    avg_fill_latency_ms: float = 0.0
    signal_count: int = 0

    @property
    def fill_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.filled_trades / self.total_trades

    @property
    def partial_fill_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.partially_filled_trades / self.total_trades

    @property
    def reject_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.rejected_trades / self.total_trades


@dataclass(frozen=True)
class MetricDeviation:
    """A single metric comparison between baseline and target."""

    metric: str
    baseline_value: float
    target_value: float
    deviation_pct: float  # (target - baseline) / baseline * 100
    within_tolerance: bool
    tolerance_pct: float
    weight: float  # contribution to overall parity score


@dataclass
class ParityMetrics:
    """All metric deviations for a parity comparison."""

    deviations: list[MetricDeviation] = field(default_factory=list)

    @property
    def passing(self) -> list[MetricDeviation]:
        return [d for d in self.deviations if d.within_tolerance]

    @property
    def failing(self) -> list[MetricDeviation]:
        return [d for d in self.deviations if not d.within_tolerance]


@dataclass
class ParityReport:
    """Complete parity comparison between two strategy snapshots."""

    label: str  # e.g. "backtest_vs_paper"
    baseline: StrategySnapshot
    target: StrategySnapshot
    metrics: ParityMetrics
    score: float  # [0, 100] — weighted parity score
    passed: bool  # score >= threshold
    threshold: float
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        failing = len(self.metrics.failing)
        return (
            f"[{status}] {self.label}: score={self.score:.1f}/{self.threshold:.0f} "
            f"({failing} metric(s) outside tolerance)"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "score": self.score,
            "threshold": self.threshold,
            "passed": self.passed,
            "generated_at": self.generated_at.isoformat(),
            "failing_metrics": [
                {
                    "metric": d.metric,
                    "baseline": d.baseline_value,
                    "target": d.target_value,
                    "deviation_pct": d.deviation_pct,
                    "tolerance_pct": d.tolerance_pct,
                }
                for d in self.metrics.failing
            ],
        }


@dataclass
class ParityScoringConfig:
    """Tolerance thresholds and weights for each metric."""

    pass_threshold: float = 70.0  # minimum score to pass

    # metric → (tolerance_pct, weight)
    # tolerance: acceptable % deviation before marking as failing
    # weight: contribution to overall score (weights should sum to 1.0)
    metric_configs: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "net_pnl": (20.0, 0.25),
            "max_drawdown_pct": (15.0, 0.20),
            "win_rate": (10.0, 0.15),
            "avg_slippage_bps": (30.0, 0.15),
            "fill_rate": (5.0, 0.10),
            "reject_rate": (5.0, 0.10),
            "signal_count": (25.0, 0.05),
        }
    )


class ParityScorer:
    """Computes parity score between two StrategySnapshot instances."""

    def __init__(self, config: ParityScoringConfig | None = None) -> None:
        self._config = config or ParityScoringConfig()

    def compare(
        self,
        baseline: StrategySnapshot,
        target: StrategySnapshot,
        label: str = "",
    ) -> ParityReport:
        deviations = self._compute_deviations(baseline, target)
        metrics = ParityMetrics(deviations=deviations)
        score = self._compute_score(deviations)
        passed = score >= self._config.pass_threshold

        return ParityReport(
            label=label or f"{baseline.environment}_vs_{target.environment}",
            baseline=baseline,
            target=target,
            metrics=metrics,
            score=score,
            passed=passed,
            threshold=self._config.pass_threshold,
        )

    def _compute_deviations(
        self,
        baseline: StrategySnapshot,
        target: StrategySnapshot,
    ) -> list[MetricDeviation]:
        def _val(snap: StrategySnapshot, metric: str) -> float:
            if metric == "net_pnl":
                return float(snap.net_pnl)
            if metric == "max_drawdown_pct":
                return snap.max_drawdown_pct
            if metric == "win_rate":
                return snap.win_rate
            if metric == "avg_slippage_bps":
                return snap.avg_slippage_bps
            if metric == "fill_rate":
                return snap.fill_rate
            if metric == "reject_rate":
                return snap.reject_rate
            if metric == "signal_count":
                return float(snap.signal_count)
            return 0.0

        results = []
        for metric, (tolerance, weight) in self._config.metric_configs.items():
            bv = _val(baseline, metric)
            tv = _val(target, metric)
            if bv == 0:
                dev_pct = abs(tv) * 100.0 if tv != 0 else 0.0
            else:
                dev_pct = abs((tv - bv) / bv) * 100.0
            results.append(
                MetricDeviation(
                    metric=metric,
                    baseline_value=bv,
                    target_value=tv,
                    deviation_pct=dev_pct,
                    within_tolerance=dev_pct <= tolerance,
                    tolerance_pct=tolerance,
                    weight=weight,
                )
            )
        return results

    def _compute_score(self, deviations: list[MetricDeviation]) -> float:
        if not deviations:
            return 0.0
        total = sum(d.weight * (100.0 if d.within_tolerance else 0.0) for d in deviations)
        total_weight = sum(d.weight for d in deviations)
        return (total / total_weight) if total_weight > 0 else 0.0
