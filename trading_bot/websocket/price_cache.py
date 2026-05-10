"""In-memory cache for the latest price tick per symbol.

Module-level singleton via get_price_cache() — safe to call from anywhere
(dashboard, scheduler, strategy engine) without circular imports.
"""

from __future__ import annotations

from trading_bot.core.models import PriceTick

_cache: PriceCache | None = None


class PriceCache:
    """Holds the most recent PriceTick per symbol (keyed by Binance symbol e.g. BTCUSDT)."""

    def __init__(self) -> None:
        self._ticks: dict[str, PriceTick] = {}

    async def update(self, tick: PriceTick) -> None:
        self._ticks[tick.symbol] = tick

    def get(self, symbol: str) -> PriceTick | None:
        return self._ticks.get(symbol)

    def snapshot(self) -> dict[str, PriceTick]:
        return dict(self._ticks)


def get_price_cache() -> PriceCache:
    global _cache
    if _cache is None:
        _cache = PriceCache()
    return _cache
