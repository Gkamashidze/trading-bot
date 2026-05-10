"""OMS <> Exchange reconciliation.

Runs periodically (default: every 60 s) and compares:
  - Open order count: OMS vs exchange
  - exchange_order_id cross-check: OMS orders not found on exchange
  - Balance: OMS cash vs exchange reported balance
  - Positions: OMS position values vs exchange positions

Severity classification:
  OK       — no discrepancies
  WARNING  — minor drift (< tolerance threshold)
  CRITICAL — significant mismatch; new orders are auto-blocked

On CRITICAL: new order submissions are blocked until an operator
calls reconciler.clear_block() or a clean reconciliation run completes.

Operator runbook: trading_bot/docs/runbooks/reconciliation-mismatch.md

The reconciler uses ClockInterface so it can be tested with FakeClock.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from trading_bot.core.contracts import ExchangeInterface
from trading_bot.core.events import ReconciliationEvent
from trading_bot.core.models import ExchangeId, OrderStatus
from trading_bot.observability.logging import get_logger
from trading_bot.oms.tracker import get_order_tracker
from trading_bot.portfolio.manager import get_portfolio_manager
from trading_bot.utils.clock import ClockInterface, WallClock

log = get_logger(__name__)

_OPEN_STATUSES = frozenset({OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED})

# Tolerance before a balance difference is flagged
_BALANCE_WARN_THRESHOLD = Decimal("1.00")  # $1 drift → warning
_BALANCE_CRITICAL_THRESHOLD = Decimal("10.00")  # $10 drift → critical


class ReconciliationSeverity(StrEnum):
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class ReconciliationReport:
    """Full reconciliation report including all check dimensions."""

    severity: ReconciliationSeverity
    order_discrepancies: list[str]
    balance_discrepancies: list[str]
    position_discrepancies: list[str]
    orders_blocked: bool  # True if new orders are being blocked
    run_at: datetime
    run_count: int
    mismatch_count: int


class Reconciler:
    """Periodic OMS <> exchange state reconciler.

    Checks three dimensions per run:
      1. Open orders — count + exchange_order_id cross-check
      2. Balance — OMS cash vs exchange reported USDT balance
      3. Positions — OMS positions vs exchange positions (future: when exchange returns positions)

    Severity escalation:
      any balance drift > CRITICAL threshold → ReconciliationSeverity.CRITICAL
      → sets _orders_blocked=True (checked by order router before submission)

    Call clear_block() to resume order submission after operator review.
    """

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
        self._orders_blocked: bool = False
        self._last_report: ReconciliationReport | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def orders_blocked(self) -> bool:
        """True when a CRITICAL mismatch is blocking new order submissions."""
        return self._orders_blocked

    def clear_block(self) -> None:
        """Operator-invoked: resume order submission after reviewing the mismatch."""
        if self._orders_blocked:
            log.warning(
                "reconciler_block_cleared",
                exchange=self._exchange_id,
                operator="operator",
            )
        self._orders_blocked = False

    async def run_once(self) -> ReconciliationReport:
        """Perform a full reconciliation pass. Returns the report regardless of outcome."""
        order_discrepancies = await self._check_orders()
        balance_discrepancies = await self._check_balances()
        # Position check: placeholder — requires exchange position API (Stage 5+)
        position_discrepancies: list[str] = []

        all_discrepancies = order_discrepancies + balance_discrepancies + position_discrepancies
        severity = self._classify_severity(
            order_discrepancies, balance_discrepancies, position_discrepancies
        )

        if severity == ReconciliationSeverity.CRITICAL:
            self._orders_blocked = True
            log.error(
                "reconciliation_critical",
                exchange=self._exchange_id,
                order_discrepancies=order_discrepancies,
                balance_discrepancies=balance_discrepancies,
                orders_blocked=True,
                runbook="trading_bot/docs/runbooks/reconciliation-mismatch.md",
            )
        elif all_discrepancies:
            self._mismatch_count += 1
            log.warning(
                "reconciliation_mismatch",
                exchange=self._exchange_id,
                severity=severity,
                discrepancies=all_discrepancies,
                runbook="trading_bot/docs/runbooks/reconciliation-mismatch.md",
            )
        else:
            # Clean run — lift any previous block
            if self._orders_blocked:
                log.info("reconciler_auto_cleared_block", exchange=self._exchange_id)
                self._orders_blocked = False
            log.info(
                "reconciliation_ok",
                exchange=self._exchange_id,
                run_count=self._run_count,
            )

        self._run_count += 1
        self._last_run = self._clock.utc_now()

        report = ReconciliationReport(
            severity=severity,
            order_discrepancies=order_discrepancies,
            balance_discrepancies=balance_discrepancies,
            position_discrepancies=position_discrepancies,
            orders_blocked=self._orders_blocked,
            run_at=self._last_run,
            run_count=self._run_count,
            mismatch_count=self._mismatch_count,
        )
        self._last_report = report
        return report

    async def run_once_as_event(self) -> ReconciliationEvent:
        """Backward-compatible wrapper: run and return legacy ReconciliationEvent."""
        report = await self.run_once()
        all_disc = (
            report.order_discrepancies
            + report.balance_discrepancies
            + report.position_discrepancies
        )
        tracker = get_order_tracker()
        oms_open = [o for o in tracker.recent(n=100) if o.status in _OPEN_STATUSES]
        return ReconciliationEvent(
            exchange=self._exchange_id,
            oms_position_count=len(oms_open),
            exchange_position_count=0,
            matched=len(all_disc) == 0,
            discrepancies=all_disc,
        )

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

    # ── Check methods ─────────────────────────────────────────────────────────

    async def _check_orders(self) -> list[str]:
        """Compare OMS open orders vs exchange open orders."""
        tracker = get_order_tracker()
        oms_open = [o for o in tracker.recent(n=100) if o.status in _OPEN_STATUSES]

        try:
            exchange_open: list[dict[str, object]] = await self._exchange.fetch_open_orders()
        except Exception as exc:
            log.error(
                "reconciler_exchange_order_fetch_failed",
                exchange=self._exchange_id,
                error=str(exc),
            )
            return [f"exchange order fetch failed: {exc}"]

        discrepancies: list[str] = []
        oms_count = len(oms_open)
        exchange_count = len(exchange_open)

        if oms_count != exchange_count:
            discrepancies.append(
                f"order count mismatch: OMS={oms_count}, exchange={exchange_count}"
            )

        oms_exchange_ids = {o.exchange_order_id for o in oms_open if o.exchange_order_id}
        exchange_ids = {
            str(o.get("orderId", o.get("id", "")))
            for o in exchange_open
            if o.get("orderId") or o.get("id")
        }
        ghost_orders = oms_exchange_ids - exchange_ids
        if ghost_orders:
            discrepancies.append(f"ghost orders (OMS only): {sorted(ghost_orders)}")

        return discrepancies

    async def _check_balances(self) -> list[str]:
        """Compare OMS cash balance vs exchange reported balance."""
        try:
            exchange_balances = await self._exchange.fetch_balances()
        except Exception as exc:
            log.warning(
                "reconciler_balance_fetch_failed",
                exchange=self._exchange_id,
                error=str(exc),
            )
            return [f"balance fetch failed: {exc}"]

        # Get OMS cash balance
        try:
            snapshot = get_portfolio_manager().get_snapshot()
            oms_cash = snapshot.cash_balance
        except Exception as exc:
            log.warning("reconciler_portfolio_fetch_failed", error=str(exc))
            return []  # Can't compare without OMS state — skip

        # Compare USDT (primary quote currency)
        exchange_usdt = exchange_balances.get("USDT", Decimal("0"))
        drift = abs(oms_cash - exchange_usdt)

        if drift >= _BALANCE_CRITICAL_THRESHOLD:
            return [
                f"USDT balance CRITICAL drift: OMS={oms_cash:.2f}, exchange={exchange_usdt:.2f}, "
                f"diff={drift:.2f} >= threshold={_BALANCE_CRITICAL_THRESHOLD}"
            ]
        if drift >= _BALANCE_WARN_THRESHOLD:
            return [
                f"USDT balance drift: OMS={oms_cash:.2f}, exchange={exchange_usdt:.2f}, "
                f"diff={drift:.2f}"
            ]
        return []

    # ── Severity classification ───────────────────────────────────────────────

    @staticmethod
    def _classify_severity(
        order_discrepancies: list[str],
        balance_discrepancies: list[str],
        position_discrepancies: list[str],
    ) -> ReconciliationSeverity:
        all_disc = order_discrepancies + balance_discrepancies + position_discrepancies
        if not all_disc:
            return ReconciliationSeverity.OK

        # Any "CRITICAL" keyword in balance → critical severity
        if any("CRITICAL" in d for d in balance_discrepancies):
            return ReconciliationSeverity.CRITICAL

        # Ghost orders or multiple discrepancies → critical
        if any("ghost" in d for d in order_discrepancies):
            return ReconciliationSeverity.CRITICAL

        return ReconciliationSeverity.WARNING

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

    @property
    def last_report(self) -> ReconciliationReport | None:
        return self._last_report


# ---------------------------------------------------------------------------
# Module-level singleton + helpers for operator console
# ---------------------------------------------------------------------------

_reconciler_instance: Reconciler | None = None


def get_reconciler() -> Reconciler | None:
    """Return the active Reconciler singleton (None if not yet initialised)."""
    return _reconciler_instance


def set_reconciler(r: Reconciler) -> None:
    """Register the active Reconciler singleton (called at startup)."""
    global _reconciler_instance
    _reconciler_instance = r


def get_last_reconciliation_event() -> ReconciliationEvent | None:
    """Return the most recent ReconciliationEvent, or None if no run yet."""
    r = _reconciler_instance
    if r is None or r.last_report is None:
        return None
    report = r.last_report
    all_disc = (
        report.order_discrepancies + report.balance_discrepancies + report.position_discrepancies
    )
    return ReconciliationEvent(
        exchange=r._exchange_id,
        oms_position_count=0,
        exchange_position_count=0,
        matched=report.severity == ReconciliationSeverity.OK,
        discrepancies=all_disc,
    )
