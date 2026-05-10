"""Tests for Stage 8 Strategy Promotion Pipeline."""

from __future__ import annotations

from trading_bot.promotion.pipeline import (
    PromotionTier,
    StrategyMetrics,
    StrategyPromotion,
    get_all_promotions,
    get_promotion,
    register_strategy,
)


def _good_metrics(tier: PromotionTier) -> StrategyMetrics:
    """Metrics that comfortably pass the gate for the given tier."""
    if tier == PromotionTier.SHADOW:
        return StrategyMetrics(
            days_running=10, sharpe_ratio=0.8, max_drawdown_pct=0.10, win_rate=0.50, total_trades=15
        )
    if tier == PromotionTier.PAPER:
        return StrategyMetrics(
            days_running=45, sharpe_ratio=1.0, max_drawdown_pct=0.08, win_rate=0.52, total_trades=30
        )
    return StrategyMetrics(
        days_running=120, sharpe_ratio=1.2, max_drawdown_pct=0.07, win_rate=0.55, total_trades=60
    )


def _bad_metrics() -> StrategyMetrics:
    return StrategyMetrics(
        days_running=1, sharpe_ratio=0.1, max_drawdown_pct=0.50, win_rate=0.20, total_trades=1
    )


class TestCanAdvance:
    def test_passes_shadow_gate(self) -> None:
        promo = StrategyPromotion(strategy_id="test")
        eligible, failures = promo.can_advance(_good_metrics(PromotionTier.SHADOW))
        assert eligible is True
        assert failures == []

    def test_fails_with_insufficient_days(self) -> None:
        promo = StrategyPromotion(strategy_id="test")
        metrics = _good_metrics(PromotionTier.SHADOW)
        metrics = StrategyMetrics(
            days_running=2,
            sharpe_ratio=metrics.sharpe_ratio,
            max_drawdown_pct=metrics.max_drawdown_pct,
            win_rate=metrics.win_rate,
            total_trades=metrics.total_trades,
        )
        eligible, failures = promo.can_advance(metrics)
        assert eligible is False
        assert any("days" in f for f in failures)

    def test_fails_with_high_drawdown(self) -> None:
        promo = StrategyPromotion(strategy_id="test")
        metrics = StrategyMetrics(
            days_running=10, sharpe_ratio=0.8, max_drawdown_pct=0.30, win_rate=0.50, total_trades=15
        )
        eligible, failures = promo.can_advance(metrics)
        assert eligible is False
        assert any("drawdown" in f for f in failures)

    def test_multiple_failure_reasons(self) -> None:
        promo = StrategyPromotion(strategy_id="test")
        _, failures = promo.can_advance(_bad_metrics())
        assert len(failures) >= 3

    def test_live_tier_cannot_advance(self) -> None:
        promo = StrategyPromotion(strategy_id="test", current_tier=PromotionTier.LIVE)
        eligible, _failures = promo.can_advance(_good_metrics(PromotionTier.SHADOW))
        assert eligible is False


class TestAdvance:
    def test_advance_shadow_to_paper(self) -> None:
        promo = StrategyPromotion(strategy_id="sma")
        new_tier = promo.advance(_good_metrics(PromotionTier.SHADOW), require_registry=False)
        assert new_tier == PromotionTier.PAPER
        assert promo.current_tier == PromotionTier.PAPER

    def test_advance_records_history(self) -> None:
        promo = StrategyPromotion(strategy_id="sma")
        promo.advance(_good_metrics(PromotionTier.SHADOW), require_registry=False)
        assert len(promo.history) == 1
        assert promo.history[0][0] == PromotionTier.SHADOW

    def test_advance_returns_none_on_failure(self) -> None:
        promo = StrategyPromotion(strategy_id="sma")
        result = promo.advance(_bad_metrics(), require_registry=False)
        assert result is None
        assert promo.current_tier == PromotionTier.SHADOW

    def test_sequential_promotion(self) -> None:
        promo = StrategyPromotion(strategy_id="sma")
        promo.advance(_good_metrics(PromotionTier.SHADOW), require_registry=False)
        promo.advance(_good_metrics(PromotionTier.PAPER), require_registry=False)
        assert promo.current_tier == PromotionTier.MICRO_LIVE
        assert len(promo.history) == 2


class TestNextGate:
    def test_shadow_has_gate(self) -> None:
        promo = StrategyPromotion(strategy_id="test")
        gate = promo.next_gate
        assert gate is not None
        assert gate.tier == PromotionTier.SHADOW

    def test_live_has_no_gate(self) -> None:
        promo = StrategyPromotion(strategy_id="test", current_tier=PromotionTier.LIVE)
        assert promo.next_gate is None


class TestRegistry:
    def test_register_and_get(self) -> None:
        register_strategy("my_strategy")
        promo = get_promotion("my_strategy")
        assert promo is not None
        assert promo.current_tier == PromotionTier.SHADOW

    def test_register_idempotent(self) -> None:
        register_strategy("idempotent_strat")
        register_strategy("idempotent_strat")
        assert get_promotion("idempotent_strat") is not None

    def test_get_returns_none_for_unknown(self) -> None:
        assert get_promotion("nonexistent_xyz") is None

    def test_get_all_returns_list(self) -> None:
        register_strategy("list_test_strat")
        all_promos = get_all_promotions()
        assert isinstance(all_promos, list)
        ids = [p.strategy_id for p in all_promos]
        assert "list_test_strat" in ids
