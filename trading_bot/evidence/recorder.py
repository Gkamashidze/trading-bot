"""Bridge execution events into the Paper Testing Evidence Store.

Gate 0 grades the evidence store (trade count, round-trips, signals), but the
execution path historically wrote only to the in-memory TCA tracker, accounting
ledger, and OMS — never to the evidence store. This module is that missing
bridge: the router calls record_fill_evidence() after every paper fill, and the
strategy runner calls record_signal_evidence() after every signal refresh.

Design rules:
- Best-effort, non-blocking: an evidence write failure NEVER breaks trading.
  Every insert is wrapped so exceptions are logged and swallowed.
- Guarded on an active paper session + an initialised evidence store. If either
  is absent (DB off, evidence disabled), recording is a no-op.
- Idempotent: deterministic idempotency keys + ON CONFLICT DO NOTHING mean a
  replayed fill or a double signal refresh in the same minute is deduplicated.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from trading_bot.evidence.models import (
    AccountingEvidenceRecord,
    ReconciliationEvidenceReport,
    ReconciliationSeverity,
    SignalEvidenceSnapshot,
    TCAEvidenceRecord,
)
from trading_bot.evidence.store import (
    EvidenceStore,
    get_current_session_id,
    get_evidence_store,
)
from trading_bot.observability.logging import get_logger
from trading_bot.oms.reconciler import ReconciliationReport
from trading_bot.strategies.base import StrategyResult

log = get_logger(__name__)


def _dec(value: object) -> Decimal:
    """Coerce any numeric-ish value to Decimal via str (avoids float noise)."""
    return Decimal(str(value))


def _idem(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _active_store() -> tuple[EvidenceStore, uuid.UUID] | None:
    """Return (store, session_id) when evidence capture is active, else None."""
    session_id = get_current_session_id()
    if session_id is None:
        return None
    try:
        store = get_evidence_store()
    except RuntimeError:
        return None
    return store, session_id


async def record_fill_evidence(
    *,
    order_id: str,
    symbol: str,
    strategy_id: str,
    side: str,
    signal_price: object,
    fill_price: object,
    quantity: object,
    fee_paid: object,
    slippage_pct: object,
    slippage_usdt: object,
    latency_ms: object,
    quality_score: str,
    outcome: str,
    realized_pnl: Decimal | None = None,
    cost_basis: Decimal | None = None,
    lot_id: str | None = None,
) -> None:
    """Persist a paper fill as a TCA record + accounting record in the evidence store.

    A SELL that realises PnL (realized_pnl set) is a completed round-trip; the
    evidence store counts those via count_round_trips().
    """
    active = _active_store()
    if active is None:
        return
    store, session_id = active
    now = datetime.now(UTC)

    try:
        await store.insert_tca_record(
            TCAEvidenceRecord(
                session_id=session_id,
                captured_at=now,
                order_id=order_id,
                symbol=symbol,
                strategy_id=strategy_id,
                side=side,
                signal_price=_dec(signal_price),
                fill_price=_dec(fill_price),
                quantity=_dec(quantity),
                fee_paid=_dec(fee_paid),
                slippage_pct=_dec(slippage_pct),
                slippage_usdt=_dec(slippage_usdt),
                latency_ms=_dec(latency_ms),
                quality_score=quality_score,
                outcome=outcome,
                idempotency_key=f"tca:{order_id}",
            )
        )
        await store.insert_accounting_record(
            AccountingEvidenceRecord(
                session_id=session_id,
                captured_at=now,
                order_id=order_id,
                symbol=symbol,
                side=side,
                quantity=_dec(quantity),
                price=_dec(fill_price),
                fee_usdt=_dec(fee_paid),
                realized_pnl=realized_pnl,
                cost_basis=cost_basis,
                lot_id=lot_id,
                idempotency_key=f"acct:{order_id}",
            )
        )
    except Exception as exc:  # never break trading on an evidence write
        log.warning("evidence_fill_record_failed", order_id=order_id, error=str(exc))


async def record_signal_evidence(results: Iterable[StrategyResult]) -> None:
    """Persist each computed strategy signal as a SignalEvidenceSnapshot.

    Idempotency key buckets by minute so a startup + scheduled refresh in the
    same minute collapse to one row per (symbol, strategy, signal).
    """
    active = _active_store()
    if active is None:
        return
    store, session_id = active
    now = datetime.now(UTC)
    bucket = now.strftime("%Y%m%d%H%M")

    for r in results:
        try:
            await store.insert_signal_snapshot(
                SignalEvidenceSnapshot(
                    session_id=session_id,
                    captured_at=now,
                    symbol=r.symbol,
                    strategy_id=r.strategy_id,
                    signal=r.signal,
                    strength=_dec(r.strength),
                    indicators=dict(r.indicators),
                    bars_used=r.bars_used,
                    idempotency_key=_idem("signal", r.symbol, r.strategy_id, r.signal, bucket),
                )
            )
        except Exception as exc:  # never break the signal refresh on evidence
            log.warning(
                "evidence_signal_record_failed",
                symbol=r.symbol,
                strategy_id=r.strategy_id,
                error=str(exc),
            )


async def record_reconciliation_evidence(report: ReconciliationReport) -> None:
    """Persist a reconciliation run as a ReconciliationEvidenceReport.

    Idempotency key buckets by run minute so a coalesced double-fire dedupes.
    """
    active = _active_store()
    if active is None:
        return
    store, session_id = active
    bucket = report.run_at.strftime("%Y%m%d%H%M")

    try:
        await store.insert_reconciliation_report(
            ReconciliationEvidenceReport(
                session_id=session_id,
                run_at=report.run_at,
                severity=ReconciliationSeverity(report.severity.value),
                order_discrepancies=list(report.order_discrepancies),
                balance_discrepancies=list(report.balance_discrepancies),
                position_discrepancies=list(report.position_discrepancies),
                orders_blocked=report.orders_blocked,
                mismatch_count=report.mismatch_count,
                idempotency_key=_idem("recon", bucket),
            )
        )
    except Exception as exc:  # never break the scheduler on an evidence write
        log.warning("evidence_reconciliation_record_failed", error=str(exc))
