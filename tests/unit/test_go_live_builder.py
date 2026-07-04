"""Unit tests for the GoLiveGate evidence builder + the paper-evidence criterion.

Covers:
- _check_paper_evidence PASS/FAIL against 30-day / 100-round-trip thresholds
- _evidence_paper_stats reads days + round-trips from the evidence store
- _paper_backtest_means aggregates paper + backtest metrics
- _rollback_runbook_exists reflects the (absent) rollback runbook
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.go_live import builder
from trading_bot.go_live.criteria import CriterionStatus
from trading_bot.go_live.gate import GoLiveGate
from trading_bot.promotion.pipeline import StrategyMetrics


def _gate(**kw: object) -> GoLiveGate:
    return GoLiveGate(
        audit_log=AsyncMock(),
        exchange=AsyncMock(),
        min_paper_days=30,
        min_round_trips=100,
        **kw,  # type: ignore[arg-type]
    )


class TestPaperEvidenceCriterion:
    @pytest.mark.asyncio
    async def test_pass_when_thresholds_met(self) -> None:
        gate = _gate(paper_trading_days=49, paper_round_trips=120)
        status, detail = await gate._check_paper_evidence()
        assert status == CriterionStatus.PASS
        assert "49 days" in detail

    @pytest.mark.asyncio
    async def test_fail_when_too_few_round_trips(self) -> None:
        gate = _gate(paper_trading_days=49, paper_round_trips=42)
        status, detail = await gate._check_paper_evidence()
        assert status == CriterionStatus.FAIL
        assert "round-trips" in detail

    @pytest.mark.asyncio
    async def test_fail_when_too_few_days(self) -> None:
        gate = _gate(paper_trading_days=10, paper_round_trips=200)
        status, _ = await gate._check_paper_evidence()
        assert status == CriterionStatus.FAIL


class TestEvidencePaperStats:
    @pytest.mark.asyncio
    async def test_reads_days_and_round_trips(self) -> None:
        store = MagicMock()
        store.list_daily_summaries = AsyncMock(return_value=[{}] * 49)
        store.count_round_trips = AsyncMock(return_value=78)
        session = MagicMock()

        with (
            patch("trading_bot.evidence.get_evidence_store", return_value=store),
            patch("trading_bot.evidence.get_current_session_id", return_value=session),
        ):
            days, trips = await builder._evidence_paper_stats(MagicMock())

        assert days == 49
        assert trips == 78

    @pytest.mark.asyncio
    async def test_zero_when_no_session(self) -> None:
        store = MagicMock()
        with (
            patch("trading_bot.evidence.get_evidence_store", return_value=store),
            patch("trading_bot.evidence.get_current_session_id", return_value=None),
        ):
            days, trips = await builder._evidence_paper_stats(MagicMock())
        assert (days, trips) == (0, 0)


class TestPaperBacktestMeans:
    @pytest.mark.asyncio
    async def test_aggregates_means(self) -> None:
        entry = MagicMock()
        entry.strategy_id = "sma"
        registry = MagicMock()
        registry.all_entries.return_value = [entry]

        paper = StrategyMetrics(
            days_running=40, sharpe_ratio=1.0, max_drawdown_pct=0.08, win_rate=0.5, total_trades=40
        )
        bt = MagicMock()
        bt.metrics.win_rate = 0.6
        bt.metrics.max_drawdown_pct = 0.10

        with (
            patch("trading_bot.strategies.registry.get_strategy_registry", return_value=registry),
            patch(
                "trading_bot.promotion.pipeline.collect_strategy_metrics",
                AsyncMock(return_value=paper),
            ),
            patch("trading_bot.backtesting.runner.get_latest_backtest", return_value=[bt]),
        ):
            p_win, p_dd, b_win, b_dd = await builder._paper_backtest_means(MagicMock())

        assert p_win == 0.5
        assert p_dd == 0.08
        assert b_win == 0.6
        assert b_dd == 0.10


def test_rollback_runbook_absent() -> None:
    # The deployment-rollback runbook has not been written yet — check is honest.
    assert builder._rollback_runbook_exists() is False
