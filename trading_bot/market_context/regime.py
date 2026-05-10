"""Rule-based market regime classifier.

Classifies the current market environment into one of three regimes
based on Fear & Greed, funding rate, and macro signals.

Regime affects strategy signal strength (via _apply_context in runner.py)
but never flips direction — conservative approach.
"""

from __future__ import annotations

from enum import StrEnum

from trading_bot.market_context import MarketContext


class MarketRegime(StrEnum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    NEUTRAL = "neutral"


_REGIME_LABELS_GE = {
    MarketRegime.RISK_ON: "Risk-On 🟢",
    MarketRegime.RISK_OFF: "Risk-Off 🔴",
    MarketRegime.NEUTRAL: "ნეიტრალური ⚪",
}

_RISK_OFF_SCORE_THRESHOLD = 2
_RISK_ON_SCORE_THRESHOLD = 2


def _risk_off_score(ctx: MarketContext) -> int:
    """Count how many risk-off conditions are active (0-4)."""
    score = 0
    if ctx.is_extreme_fear():
        score += 2  # strong signal — weight double
    if ctx.is_high_rates():
        score += 1
    if ctx.is_high_inflation():
        score += 1
    return score


def _risk_on_score(ctx: MarketContext) -> int:
    """Count how many risk-on conditions are active (0-3)."""
    score = 0
    if ctx.fear_greed_value is not None and ctx.fear_greed_value >= 60:
        score += 1
    if ctx.is_negative_funding():
        score += 1  # shorts paying longs = bullish pressure
    if ctx.fed_funds_rate is not None and ctx.fed_funds_rate < 3.0:
        score += 1
    return score


def classify_regime(ctx: MarketContext) -> MarketRegime:
    """Classify market regime from a MarketContext snapshot.

    Returns NEUTRAL when signals conflict or data is missing.
    Risk-off takes priority over risk-on (conservative by design).
    """
    off_score = _risk_off_score(ctx)
    on_score = _risk_on_score(ctx)

    if off_score >= _RISK_OFF_SCORE_THRESHOLD:
        return MarketRegime.RISK_OFF
    if on_score >= _RISK_ON_SCORE_THRESHOLD and off_score == 0:
        return MarketRegime.RISK_ON
    return MarketRegime.NEUTRAL


def regime_label(regime: MarketRegime) -> str:
    return _REGIME_LABELS_GE[regime]
