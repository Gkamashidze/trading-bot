"""UUID v7 generation for idempotency keys.

UUID v7 is time-ordered (monotonically increasing by millisecond), which
makes it ideal for idempotency keys in a trading system:
- Time-ordered: easier to debug (keys sort chronologically)
- Globally unique: no collision risk across distributed instances
- Standard format: works with any UUID column in Postgres

UUID v7 spec: https://www.ietf.org/archive/id/draft-peabody-dispatch-new-uuid-format-04.txt
"""

from __future__ import annotations

import time
import uuid


def generate_idempotency_key() -> str:
    """Generate a UUID v7 (time-ordered) idempotency key.

    Falls back to UUID v4 with timestamp prefix if uuid-utils is unavailable.
    Format: standard UUID string e.g. "018f4e3b-1234-7abc-..."
    """
    try:
        import uuid_utils

        return str(uuid_utils.uuid7())
    except ImportError:
        # Fallback: UUID v4 with ms-precision timestamp prefix
        # Not truly v7, but time-prefixed for debuggability
        ts_ms = int(time.time() * 1000)
        ts_hex = f"{ts_ms:012x}"
        tail = uuid.uuid4().hex[12:]
        combined = f"{ts_hex}{tail}"
        # Format as UUID string
        a, b, c, d, e = (
            combined[0:8],
            combined[8:12],
            combined[13:16],
            combined[16:20],
            combined[20:32],
        )
        return f"{a}-{b}-7{c}-{d}-{e}"


def idempotency_key_for_order(
    strategy_id: str,
    symbol: str,
    side: str,
    signal_id: str,
) -> str:
    """Deterministic idempotency key for a specific order attempt.

    Using signal_id as the base ensures that retrying the same signal
    always produces the same key — idempotent at the signal level.
    """
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # DNS namespace
    name = f"{strategy_id}:{symbol}:{side}:{signal_id}"
    return str(uuid.uuid5(namespace, name))
