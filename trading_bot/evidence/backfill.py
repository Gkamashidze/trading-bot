"""Backfill the evidence store from the paper_orders OMS table.

The evidence recorder (evidence/recorder.py) was wired only recently. Weeks of
paper fills already live durably in paper_orders but never reached
evidence_tca_records, so the Gate 0 report read trade_count=0 despite real
trading. This one-shot backfill reconstructs the missing TCA + accounting
evidence from that order history.

Idempotent: uses the SAME deterministic idempotency keys as the live recorder
(tca:{order_id} / acct:{order_id}), so backfilled rows and any live-captured
rows dedupe naturally via ON CONFLICT DO NOTHING. Safe to run on every startup.

Realized PnL / cost-basis is reconstructed by replaying the filled orders in
chronological order through a fresh FIFO AccountingLedger — the same matching
the live path uses — so round-trip counting works on backfilled data.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import asyncpg

from trading_bot.accounting.ledger import AccountingLedger
from trading_bot.evidence.models import AccountingEvidenceRecord, TCAEvidenceRecord
from trading_bot.evidence.store import EvidenceStore
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_TAKER_FEE_RATE = Decimal("0.001")  # 0.1% — mirrors the router's fee assumption
_FILLED_STATUSES = ["filled", "partially_filled"]


async def needs_backfill(pool: asyncpg.Pool, session_id: uuid.UUID) -> bool:
    """True when filled paper_orders outnumber recorded TCA evidence rows."""
    async with pool.acquire() as conn:
        filled = await conn.fetchval(
            "SELECT COUNT(*) FROM paper_orders WHERE status = ANY($1::text[])",
            _FILLED_STATUSES,
        )
        recorded = await conn.fetchval(
            "SELECT COUNT(*) FROM evidence_tca_records WHERE session_id = $1",
            session_id,
        )
    return int(filled or 0) > int(recorded or 0)


async def backfill_evidence_from_paper_orders(
    pool: asyncpg.Pool,
    store: EvidenceStore,
    session_id: uuid.UUID,
) -> int:
    """Reconstruct TCA + accounting evidence from paper_orders. Returns rows inserted."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT order_id, strategy_id, symbol, side, filled_qty, fill_price,
                   status, created_at
            FROM paper_orders
            WHERE status = ANY($1::text[])
                  AND filled_qty IS NOT NULL
                  AND fill_price IS NOT NULL
            ORDER BY created_at ASC
            """,
            _FILLED_STATUSES,
        )

    ledger = AccountingLedger()
    inserted = 0
    for row in rows:
        order_id = row["order_id"]
        symbol = row["symbol"]
        side = str(row["side"])
        qty = Decimal(str(row["filled_qty"]))
        price = Decimal(str(row["fill_price"]))
        fee = qty * price * _TAKER_FEE_RATE
        created_at = row["created_at"]
        outcome = "partial" if row["status"] == "partially_filled" else "filled"

        lot = ledger.record_trade(
            symbol=symbol,
            side=side,
            quantity=qty,
            price=price,
            fee_usdt=fee,
            order_id=order_id,
            trade_time=created_at,
        )
        realized = ledger.realized_for_sell(lot.lot_id) if side.upper() == "SELL" else None
        realized_pnl, cost_basis = realized if realized is not None else (None, None)

        try:
            did_insert = await store.insert_tca_record(
                TCAEvidenceRecord(
                    session_id=session_id,
                    captured_at=created_at,
                    order_id=order_id,
                    symbol=symbol,
                    strategy_id=row["strategy_id"] or "",
                    side=side,
                    signal_price=price,  # paper fills at signal price; no stored signal
                    fill_price=price,
                    quantity=qty,
                    fee_paid=fee,
                    outcome=outcome,
                    idempotency_key=f"tca:{order_id}",
                )
            )
            await store.insert_accounting_record(
                AccountingEvidenceRecord(
                    session_id=session_id,
                    captured_at=created_at,
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    price=price,
                    fee_usdt=fee,
                    realized_pnl=realized_pnl,
                    cost_basis=cost_basis,
                    lot_id=lot.lot_id,
                    idempotency_key=f"acct:{order_id}",
                )
            )
            if did_insert:
                inserted += 1
        except Exception as exc:  # one bad row must not abort the whole backfill
            log.warning("evidence_backfill_row_failed", order_id=order_id, error=str(exc))

    log.info("evidence_backfill_complete", rows_seen=len(rows), inserted=inserted)
    return inserted
