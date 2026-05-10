"""Tests for parity/report.py — ParityScorer."""

from datetime import UTC, datetime
from decimal import Decimal

from trading_bot.parity.report import (
    ParityScorer,
    ParityScoringConfig,
    StrategySnapshot,
)


def _snapshot(environment: str, net_pnl: float = 1000.0, **kwargs: object) -> StrategySnapshot:
    base = {
        "strategy_id": "sma",
        "environment": environment,
        "period_start": datetime.now(UTC),
        "period_end": datetime.now(UTC),
        "net_pnl": Decimal(str(net_pnl)),
        "total_trades": 100,
        "filled_trades": 95,
        "partially_filled_trades": 3,
        "rejected_trades": 2,
        "win_rate": 0.55,
        "avg_slippage_bps": 5.0,
        "signal_count": 110,
        "max_drawdown_pct": 0.08,
    }
    base.update(kwargs)
    return StrategySnapshot(**base)  # type: ignore[arg-type]


class TestParityScorer:
    def setup_method(self) -> None:
        self.scorer = ParityScorer()

    def test_identical_snapshots_perfect_score(self) -> None:
        bt = _snapshot("backtest")
        paper = _snapshot("paper")
        report = self.scorer.compare(bt, paper)
        assert report.passed
        assert report.score == 100.0

    def test_large_pnl_deviation_fails(self) -> None:
        # net_pnl weight=0.25; losing it alone scores 75 (above threshold=70).
        # Must fail multiple metrics to drop below 70. Fail net_pnl + win_rate + fill_rate.
        bt = _snapshot("backtest", net_pnl=1000.0, win_rate=0.55)
        paper = _snapshot("paper", net_pnl=100.0, win_rate=0.10, filled_trades=50)
        report = self.scorer.compare(bt, paper)
        assert not report.passed
        failing_names = [d.metric for d in report.metrics.failing]
        assert "net_pnl" in failing_names

    def test_small_pnl_deviation_passes(self) -> None:
        bt = _snapshot("backtest", net_pnl=1000.0)
        paper = _snapshot("paper", net_pnl=950.0)  # -5% deviation — within 20% tolerance
        report = self.scorer.compare(bt, paper)
        net_pnl_check = next(d for d in report.metrics.deviations if d.metric == "net_pnl")
        assert net_pnl_check.within_tolerance

    def test_custom_threshold(self) -> None:
        cfg = ParityScoringConfig(pass_threshold=95.0)
        scorer = ParityScorer(config=cfg)
        bt = _snapshot("backtest")
        paper = _snapshot("paper")
        report = scorer.compare(bt, paper)
        assert report.threshold == 95.0

    def test_label_defaults_to_environments(self) -> None:
        bt = _snapshot("backtest")
        paper = _snapshot("paper")
        report = self.scorer.compare(bt, paper)
        assert "backtest" in report.label
        assert "paper" in report.label

    def test_explicit_label(self) -> None:
        bt = _snapshot("backtest")
        paper = _snapshot("paper")
        report = self.scorer.compare(bt, paper, label="my_comparison")
        assert report.label == "my_comparison"

    def test_to_dict_has_required_keys(self) -> None:
        bt = _snapshot("backtest")
        paper = _snapshot("paper")
        d = self.scorer.compare(bt, paper).to_dict()
        assert "score" in d
        assert "passed" in d
        assert "failing_metrics" in d

    def test_fill_rate_property(self) -> None:
        snap = _snapshot("paper", total_trades=100, filled_trades=80)
        assert snap.fill_rate == 0.80

    def test_reject_rate_property(self) -> None:
        snap = _snapshot("paper", total_trades=100, rejected_trades=5)
        assert snap.reject_rate == 0.05

    def test_zero_trades_rates_are_zero(self) -> None:
        snap = _snapshot("paper", total_trades=0, filled_trades=0, rejected_trades=0)
        assert snap.fill_rate == 0.0
        assert snap.reject_rate == 0.0
