"""@idempotent decorator for state-changing async operations.

Usage:
    store = PostgresIdempotencyStore(pool)

    @idempotent(key_func=lambda req: req.idempotency_key, store=store)
    async def submit_order(req: OrderRequest) -> OrderState:
        ...

The decorated function will:
1. Compute the idempotency key from the first argument
2. Try to acquire the key in the store
3. If already acquired → raise IdempotencyCollisionError (duplicate blocked)
4. If acquired → execute the function
5. If the function raises → release the key so the caller can retry
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

from trading_bot.core.contracts import IdempotencyStoreInterface
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


def idempotent(
    key_func: Callable[..., str],
    store: IdempotencyStoreInterface | None = None,
    ttl_seconds: int = 604_800,
    release_on_error: bool = True,
) -> Callable[[F], F]:
    """Decorator factory for idempotent async functions.

    Args:
        key_func: Callable that extracts the idempotency key from the
                  first positional argument of the decorated function.
        store:    IdempotencyStoreInterface implementation. If None, a
                  module-level default store must be set via set_default_store().
        ttl_seconds: How long to keep the key (default: 7 days).
        release_on_error: If True, release the key on exception so retries
                          are possible. Set False if the operation is
                          partially committed (e.g. exchange order placed
                          but DB write failed — you do NOT want to retry).
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            resolved_store = store or _default_store
            if resolved_store is None:
                log.warning(
                    "idempotency_store_not_configured",
                    func=func.__name__,
                    action="skipping_check",
                )
                return await func(*args, **kwargs)

            # Extract key from first positional argument
            first_arg = args[0] if args else next(iter(kwargs.values()), None)
            key = key_func(first_arg)

            acquired = await resolved_store.acquire(key, ttl_seconds)
            if not acquired:
                log.warning(
                    "idempotent_duplicate_blocked",
                    func=func.__name__,
                    key_prefix=key[:16],
                )
                from trading_bot.core.exceptions import IdempotencyCollisionError

                raise IdempotencyCollisionError(
                    f"Duplicate call to {func.__name__} with key {key[:16]}..."
                )

            try:
                return await func(*args, **kwargs)
            except Exception:
                if release_on_error:
                    await resolved_store.release(key)
                raise

        return wrapper  # type: ignore[return-value]

    return decorator


_default_store: IdempotencyStoreInterface | None = None


def set_default_store(store: IdempotencyStoreInterface) -> None:
    """Set the module-level default idempotency store.

    Call this in main.py after the DB pool is created.
    """
    global _default_store
    _default_store = store
