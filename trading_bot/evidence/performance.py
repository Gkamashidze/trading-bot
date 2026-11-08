"""Reconstruct strategy contributions from actual fills and recorded market marks.

Each contribution is normalised to the session's original paper capital. Returns
include fees and open positions. Missing marks and cross-strategy inventory are
explicit evidence errors; neither can be used to approve promotion.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

STRATEGY_EQUITY_KEY = "__strategy_equity__"


def reconstruct_strategy_equity(
    fills: list[dict[str, Any]],
    marks: dict[str, Decimal],
    initial_capital: Decimal,
) -> dict[str, dict[str, Any]]:
    books: dict[str, Any] = {}
    for fill in fills:
        sid = str(fill["strategy_id"])
        book = books.setdefault(
            sid, {"cash": initial_capital, "positions": defaultdict(Decimal), "errors": []}
        )
        qty, price, fee = (Decimal(str(fill[k])) for k in ("quantity", "fill_price", "fee_paid"))
        if not all(v.is_finite() for v in (qty, price, fee)) or qty <= 0 or price <= 0 or fee < 0:
            book["errors"].append("invalid fill values")
            continue
        symbol = str(fill["symbol"])
        side = str(fill["side"]).lower()
        if side == "buy":
            book["cash"] -= qty * price + fee
            book["positions"][symbol] += qty
        elif side == "sell":
            book["cash"] += qty * price - fee
            book["positions"][symbol] -= qty
            if book["positions"][symbol] < 0:
                book["errors"].append(f"unmatched sell inventory: {symbol}")
        else:
            book["errors"].append("invalid fill side")

    result: dict[str, dict[str, Any]] = {}
    for sid, book in books.items():
        from trading_bot.observability.metrics import STRATEGY_EQUITY_VERIFIED, STRATEGY_PNL

        equity = book["cash"]
        for symbol, qty in book["positions"].items():
            if qty == 0:
                continue
            mark = marks.get(symbol)
            if mark is None or not mark.is_finite() or mark <= 0:
                book["errors"].append(f"fresh mark unavailable: {symbol}")
            else:
                equity += qty * mark
        errors = sorted(set(book["errors"]))
        STRATEGY_EQUITY_VERIFIED.labels(strategy=sid).set(0 if errors else 1)
        if not errors:
            STRATEGY_PNL.labels(strategy=sid).set(float(equity - initial_capital))
        result[sid] = {
            "equity": str(equity),
            "initial_capital": str(initial_capital),
            "complete": not errors,
            "errors": errors,
        }
    return result


async def capture_strategy_equity(pool: Any, session_id: Any) -> dict[str, dict[str, Any]]:
    """Build a mark-to-market snapshot; never fabricate unavailable historical marks."""
    from trading_bot.websocket.price_cache import get_price_cache

    async with pool.acquire() as conn:
        capital = await conn.fetchval(
            "SELECT paper_capital FROM evidence_sessions WHERE session_id = $1", session_id
        )
        rows = await conn.fetch(
            """SELECT strategy_id, symbol, side, quantity, fill_price, fee_paid
               FROM evidence_tca_records
               WHERE session_id = $1 AND outcome IN ('filled', 'partial')
               ORDER BY captured_at, record_id""",
            session_id,
        )
    if capital is None or Decimal(str(capital)) <= 0:
        return {}
    marks: dict[str, Decimal] = {}
    now = datetime.now(UTC)
    for symbol in {str(row["symbol"]) for row in rows}:
        tick = get_price_cache().get(symbol.replace("/", "").upper())
        if tick is not None and 0 <= (now - tick.timestamp).total_seconds() <= 120:
            marks[symbol] = tick.price
    return reconstruct_strategy_equity([dict(row) for row in rows], marks, Decimal(str(capital)))
