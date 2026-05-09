"""Feature flag system — DB-backed, in-memory cached, decorator-enforced.

All flags default to safe values (live_trading_enabled = false).
The DB is the source of truth; the YAML file provides bootstrap defaults.

Usage:
    from trading_bot.feature_flags import is_enabled, feature_required

    # Direct check
    if await is_enabled("websocket_enabled"):
        ...

    # Decorator — raises FeatureDisabledError if flag is off
    @feature_required("paper_trading_enabled")
    async def place_paper_order(req: OrderRequest) -> OrderState:
        ...
"""

from trading_bot.feature_flags.decorator import feature_required
from trading_bot.feature_flags.store import FeatureFlagStore, is_enabled

__all__ = ["FeatureFlagStore", "feature_required", "is_enabled"]
