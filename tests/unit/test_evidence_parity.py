"""Unit tests for paper↔backtest parity scoring.

Covers:
- None when no backtests exist
- None when a strategy has too little paper data
- score ~1.0 when backtest and paper metrics match
- lower score when win rate diverges
- returned as a 0-1 fraction (evidence-gate scale)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.parity import evidence_parity
from trading_bot.promotion.pipeline import StrategyMetrics


def _backtest(strategy_id: str, win_rate: float, max_dd: float) -> MagicMock:
    bt = MagicMock()
    bt.strategy_id = strategy_id
    bt.metrics.win_rate = win_rate
    bt.metrics.max_drawdown_pct = max_dd
    return bt


def _paper(win_rate: float, max_dd: float, trades: int = 40) -> StrategyMetrics:
    return StrategyMetrics(
        days_running=40,
        sharpe_ratio=1.0,
        max_drawdown_pct=max_dd,
        win_rate=win_rate,
        total_trades=trades,
    )


class TestComputeParityScore:
    @pytest.mark.asyncio
    async def test_none_when_no_backtests(self) -> None:
        with patch.object(evidence_parity, "get_latest_backtest", return_value=[]):
            assert await evidence_parity.compute_parity_score(MagicMock()) is None

    @pytest.mark.asyncio
    async def test_none_when_no_paper_data(self) -> None:
        with (
            patch.object(
                evidence_parity,
                "get_latest_backtest",
                return_value=[_backtest("sma", 0.5, 0.05)],
            ),
            patch.object(evidence_parity, "collect_strategy_metrics", AsyncMock(return_value=None)),
        ):
            assert await evidence_parity.compute_parity_score(MagicMock()) is None

    @pytest.mark.asyncio
    async def test_perfect_match_scores_one(self) -> None:
        with (
            patch.object(
                evidence_parity,
                "get_latest_backtest",
                return_value=[_backtest("sma", 0.5, 0.05)],
            ),
            patch.object(
                evidence_parity,
                "collect_strategy_metrics",
                AsyncMock(return_value=_paper(0.5, 0.05)),
            ),
        ):
            score = await evidence_parity.compute_parity_score(MagicMock())
        assert score is not None
        assert float(score) == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_win_rate_divergence_lowers_score(self) -> None:
        # win_rate weight 0.7 fails; drawdown weight 0.3 passes → 0.30 fraction
        with (
            patch.object(
                evidence_parity,
                "get_latest_backtest",
                return_value=[_backtest("sma", 0.5, 0.05)],
            ),
            patch.object(
                evidence_parity,
                "collect_strategy_metrics",
                AsyncMock(return_value=_paper(0.1, 0.05)),
            ),
        ):
            score = await evidence_parity.compute_parity_score(MagicMock())
        assert score is not None
        assert float(score) == pytest.approx(0.30)

    @pytest.mark.asyncio
    async def test_drawdown_percent_source_is_normalised(self) -> None:
        # backtest drawdown expressed as percent (5.0) vs paper fraction (0.05)
        # must be treated as equal after normalisation → perfect match
        with (
            patch.object(
                evidence_parity,
                "get_latest_backtest",
                return_value=[_backtest("sma", 0.5, 5.0)],
            ),
            patch.object(
                evidence_parity,
                "collect_strategy_metrics",
                AsyncMock(return_value=_paper(0.5, 0.05)),
            ),
        ):
            score = await evidence_parity.compute_parity_score(MagicMock())
        assert score is not None
        assert float(score) == pytest.approx(1.0)
