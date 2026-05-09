"""Idempotency subsystem — UUID v7 + Postgres-backed key store.

Every state-changing operation must acquire an idempotency key before
executing. If the key is already present (within TTL), the operation is a
duplicate and must be rejected. This prevents double-orders, double-fills,
and corrupted portfolio state on retry.

Usage:
    from trading_bot.idempotency import generate_idempotency_key, idempotent

    key = generate_idempotency_key()

    @idempotent(key_func=lambda req: req.idempotency_key)
    async def submit_order(req: OrderRequest) -> OrderState:
        ...
"""

from trading_bot.idempotency.decorator import idempotent
from trading_bot.idempotency.keys import generate_idempotency_key
from trading_bot.idempotency.store import PostgresIdempotencyStore

__all__ = ["PostgresIdempotencyStore", "generate_idempotency_key", "idempotent"]
