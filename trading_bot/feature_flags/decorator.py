"""@feature_required decorator — blocks execution if flag is disabled.

Usage:
    @feature_required("paper_trading_enabled")
    async def place_paper_order(req: OrderRequest) -> OrderState:
        ...

Raises FeatureDisabledError if the flag evaluates to False.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from trading_bot.core.exceptions import FeatureDisabledError
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


def feature_required(flag_name: str) -> Callable[[F], F]:
    """Decorator: raises FeatureDisabledError if the named flag is disabled."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            from trading_bot.feature_flags.store import is_enabled

            if not await is_enabled(flag_name):
                log.warning(
                    "feature_blocked",
                    flag_name=flag_name,
                    func=func.__name__,
                )
                raise FeatureDisabledError(flag_name)

            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
