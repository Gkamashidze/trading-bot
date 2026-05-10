"""OMS <> Exchange reconciliation.

Runs periodically (default: every 60 s) and compares:
  - Open order count: OMS vs exchange
  - exchange_order_id cross-check: OMS orders not found on exchange

On mismatch: logs an error and returns a ReconciliationEvent with discrepancies.
Operator runbook: trading_bot/docs/runbooks/reconciliation-mismatch.md

The reconciler uses ClockInterface so it can be tested with FakeClock without
real network calls or wall-clock sleeps.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from trading_bot.core.contracts import ExchangeInterface
from trading_bot.core.events import ReconciliationEvent
from trading_bot.core.models import ExchangeId, OrderStatus
from trading_bot.observability.logging import get_logger
from trading_bot.oms.tracker import get_order_tracker
from trading_bot.utils.clock import ClockInterface, WallClock

log = get_logger(__name__)

_OPEN_STATUSES = frozenset({OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED})


class Reconciler:
    """Periodic OMS <> exchange state reconciler."""

    def __init__(
        self,
        exchange: ExchangeInterface,
        exchange_id: ExchangeId,
        interval_seconds: float = 60.0,
        clock: ClockInterface | None = None,
    ) -> None:
        self._exchange = exchange
        self._exchange_id = exchange_id
        self._interval = interval_seconds
        self._clock = clock or WallClock()
        self._last_run: datetime | None = None
        self._run_count = 0
        self._mismatch_count = 0

    # ── Public API ────────────────────────────────────────────────────────────

    async def run_once(self) -> ReconciliationEvent:
        """Perform a single reconciliation pass. Returns the event regardless of outcome."""
        tracker = get_order_tracker()
        oms_open = [o for o in tracker.recent(n=100) if o.status in _OPEN_STATUSES]

        try:
            exchange_open: list[dict[str, object]] = await self._exchange.fetch_open_orders()
        except Exception as exc:
            log.error(
                "reconciler_exchange_fetch_failed",
                exchange=self._exchange_id,
                error=str(exc),
            )
            exchange_open = []

        oms_count = len(oms_open)
        exchange_count = len(exchange_open)
        discrepancies: list[str] = []

        if oms_count != exchange_count:
            discrepancies.append(
                f"OMS has {oms_count} open orders; exchange reports {exchange_count}"
            )

        # Cross-check by exchange_order_id for orders that have been acknowledged
        oms_exchange_ids = {o.exchange_order_id for o in oms_open if o.exchange_order_id}
        exchange_ids = {
            str(o.get("orderId", o.get("id", "")))
            for o in exchange_open
            if o.get("orderId") or o.get("id")
        }
        ghost_orders = oms_exchange_ids - exchange_ids
        if ghost_orders:
            discrepancies.append(f"OMS orders absent on exchange: {sorted(ghost_orders)}")

        matched = len(discrepancies) == 0
        event = ReconciliationEvent(
            exchange=self._exchange_id,
            oms_position_count=oms_count,
            exchange_position_count=exchange_count,
            matched=matched,
            discrepancies=discrepancies,
        )

        self._run_count += 1
        self._last_run = self._clock.utc_now()

        if discrepancies:
            self._mismatch_count += 1
            log.error(
                "reconciliation_mismatch",
                exchange=self._exchange_id,
                discrepancies=discrepancies,
                runbook="trading_bot/docs/runbooks/reconciliation-mismatch.md",
            )
        else:
            log.info(
                "reconciliation_ok",
                exchange=self._exchange_id,
                oms_open=oms_count,
                exchange_open=exchange_count,
                run_count=self._run_count,
            )

        return event

    async def start_background_loop(self) -> None:
        """Run reconciliation continuously at `interval_seconds`. Cancel to stop."""
        log.info(
            "reconciler_loop_started",
            exchange=self._exchange_id,
            interval_seconds=self._interval,
        )
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                log.info("reconciler_loop_cancelled", exchange=self._exchange_id)
                return
            except Exception as exc:
                log.error("reconciler_loop_error", exchange=self._exchange_id, error=str(exc))
            await self._clock.sleep(self._interval)

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def last_run(self) -> datetime | None:
        return self._last_run

    @property
    def run_count(self) -> int:
        return self._run_count

    @property
    def mismatch_count(self) -> int:
        return self._mismatch_count
