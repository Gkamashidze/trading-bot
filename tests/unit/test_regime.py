"""Tests for Stage 8 Market Regime Classifier."""

from __future__ import annotations

from datetime import UTC, datetime

from trading_bot.market_context import MarketContext
from trading_bot.market_context.regime import MarketRegime, classify_regime


def _ctx(
    fear_greed: int | None = None,
    funding_rate: float | None = None,
    fed_rate: float | None = None,
    cpi_yoy: float | None = None,
) -> MarketContext:
    return MarketContext(
        fear_greed_value=fear_greed,
        fear_greed_label=None,
        funding_rate=funding_rate,
        fed_funds_rate=fed_rate,
        cpi_yoy=cpi_yoy,
        fetched_at=datetime.now(UTC),
    )


class TestRiskOff:
    def test_extreme_fear_alone_triggers_risk_off(self) -> None:
        ctx = _ctx(fear_greed=10)
        assert classify_regime(ctx) == MarketRegime.RISK_OFF

    def test_extreme_fear_with_high_rates(self) -> None:
        ctx = _ctx(fear_greed=20, fed_rate=5.5)
        assert classify_regime(ctx) == MarketRegime.RISK_OFF

    def test_high_rates_and_inflation_triggers_risk_off(self) -> None:
        ctx = _ctx(fed_rate=5.0, cpi_yoy=6.0)
        assert classify_regime(ctx) == MarketRegime.RISK_OFF

    def test_high_rates_alone_is_not_enough(self) -> None:
        ctx = _ctx(fed_rate=5.0)
        # only 1 risk-off signal → threshold is 2
        assert classify_regime(ctx) != MarketRegime.RISK_OFF

    def test_high_inflation_alone_is_not_enough(self) -> None:
        ctx = _ctx(cpi_yoy=6.0)
        assert classify_regime(ctx) != MarketRegime.RISK_OFF


class TestRiskOn:
    def test_greed_and_negative_funding(self) -> None:
        ctx = _ctx(fear_greed=70, funding_rate=-0.0001)
        assert classify_regime(ctx) == MarketRegime.RISK_ON

    def test_greed_and_low_rates(self) -> None:
        ctx = _ctx(fear_greed=65, fed_rate=1.5)
        assert classify_regime(ctx) == MarketRegime.RISK_ON

    def test_negative_funding_and_low_rates(self) -> None:
        ctx = _ctx(funding_rate=-0.0003, fed_rate=2.0)
        assert classify_regime(ctx) == MarketRegime.RISK_ON

    def test_risk_off_overrides_risk_on(self) -> None:
        # extreme fear (risk-off score 2) + all risk-on signals
        ctx = _ctx(fear_greed=20, funding_rate=-0.0003, fed_rate=1.5)
        assert classify_regime(ctx) == MarketRegime.RISK_OFF

    def test_moderate_greed_alone_insufficient(self) -> None:
        ctx = _ctx(fear_greed=65)
        assert classify_regime(ctx) != MarketRegime.RISK_ON


class TestNeutral:
    def test_no_data_is_neutral(self) -> None:
        ctx = _ctx()
        assert classify_regime(ctx) == MarketRegime.NEUTRAL

    def test_moderate_fear_is_neutral(self) -> None:
        ctx = _ctx(fear_greed=40)
        assert classify_regime(ctx) == MarketRegime.NEUTRAL

    def test_positive_funding_low_fear_neutral(self) -> None:
        ctx = _ctx(fear_greed=50, funding_rate=0.0001)
        assert classify_regime(ctx) == MarketRegime.NEUTRAL


class TestMarketContextRegimeProperty:
    def test_regime_property_returns_string(self) -> None:
        ctx = _ctx(fear_greed=15)
        assert ctx.regime == "risk_off"

    def test_regime_property_neutral(self) -> None:
        ctx = _ctx()
        assert ctx.regime == "neutral"

    def test_regime_in_as_dict(self) -> None:
        ctx = _ctx(fear_greed=10)
        d = ctx.as_dict()
        assert "regime" in d
        assert d["regime"] == "risk_off"
