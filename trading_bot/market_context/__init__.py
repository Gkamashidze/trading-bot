"""Market context aggregator.

Combines Fear & Greed, Funding Rate, and Macro signals into one
immutable snapshot used by the strategy runner.

Usage:
    from trading_bot.market_context import get_market_context, refresh_market_context

    ctx = await refresh_market_context()   # fetches fresh data
    ctx = get_market_context()             # returns last cached snapshot (may be None)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from trading_bot.market_context.fear_greed import FearGreedProvider
from trading_bot.market_context.funding_rate import FundingRateProvider
from trading_bot.market_context.macro import MacroProvider
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class MarketContext:
    """Immutable snapshot of market-wide context signals."""

    fear_greed_value: int | None
    fear_greed_label: str | None
    funding_rate: float | None
    fed_funds_rate: float | None
    cpi_yoy: float | None
    fetched_at: datetime

    # ── Derived helpers ──────────────────────────────────────────────────

    def is_extreme_fear(self) -> bool:
        return self.fear_greed_value is not None and self.fear_greed_value <= 25

    def is_extreme_greed(self) -> bool:
        return self.fear_greed_value is not None and self.fear_greed_value >= 75

    def is_negative_funding(self) -> bool:
        return self.funding_rate is not None and self.funding_rate < 0

    def is_high_rates(self) -> bool:
        """Fed Funds Rate above 4% — risk-off environment for crypto."""
        return self.fed_funds_rate is not None and self.fed_funds_rate >= 4.0

    def is_high_inflation(self) -> bool:
        """CPI YoY above 4% — historically negative for risk assets."""
        return self.cpi_yoy is not None and self.cpi_yoy >= 4.0

    @property
    def regime(self) -> str:
        """Current market regime: 'risk_on', 'risk_off', or 'neutral'."""
        from trading_bot.market_context.regime import classify_regime

        return str(classify_regime(self))

    def as_dict(self) -> dict[str, object]:
        return {
            "fear_greed_value": self.fear_greed_value,
            "fear_greed_label": self.fear_greed_label,
            "funding_rate": self.funding_rate,
            "fed_funds_rate": self.fed_funds_rate,
            "cpi_yoy": self.cpi_yoy,
            "regime": self.regime,
            "fetched_at": self.fetched_at.isoformat(),
        }


# ── Module-level singletons ───────────────────────────────────────────────────

_fear_greed: FearGreedProvider | None = None
_funding_rate: FundingRateProvider | None = None
_macro: MacroProvider | None = None
_last_context: MarketContext | None = None


def _init_providers() -> None:
    global _fear_greed, _funding_rate, _macro
    if _fear_greed is not None:
        return

    from trading_bot.config import get_settings

    settings = get_settings()
    _fear_greed = FearGreedProvider()
    _funding_rate = FundingRateProvider()
    _macro = MacroProvider(api_key=settings.market_context.fred_api_key)


def get_market_context() -> MarketContext | None:
    """Return the last successfully fetched context snapshot. May be None on startup."""
    return _last_context


async def refresh_market_context() -> MarketContext:
    """Fetch fresh data from all providers and return a new MarketContext.

    Each provider fails independently — a single outage does not block the others.
    Failures result in None fields, not exceptions.
    """
    global _last_context

    _init_providers()
    assert _fear_greed is not None
    assert _funding_rate is not None
    assert _macro is not None

    fg_value, fg_label = await _fear_greed.fetch()
    fr = await _funding_rate.fetch()
    fed_rate, cpi_yoy = await _macro.fetch()

    ctx = MarketContext(
        fear_greed_value=fg_value,
        fear_greed_label=fg_label,
        funding_rate=fr,
        fed_funds_rate=fed_rate,
        cpi_yoy=cpi_yoy,
        fetched_at=datetime.now(UTC),
    )
    _last_context = ctx

    log.info(
        "market_context_refreshed",
        fear_greed=fg_value,
        funding_rate=fr,
        fed_rate=fed_rate,
        cpi_yoy=cpi_yoy,
    )
    return ctx
