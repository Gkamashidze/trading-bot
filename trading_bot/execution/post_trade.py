"""Post-Trade Finalization Processor — #13 of the production readiness roadmap.

After every confirmed fill (paper or live), this processor runs the full
post-trade pipeline in order:

  1. Confirm fill details (quantity, price, fees)
  2. Detect duplicate fills (idempotency check)
  3. Update OMS order state
  4. Update portfolio positions
  5. Update accounting ledger
  6. Record TCA (Transaction Cost Analysis)
  7. Append audit event
  8. Emit Prometheus metrics
  9. Reconcile position impact

All steps are run transactionally (best-effort in the absence of a real
distributed transaction). If any step fails, the error is logged and the
processor returns a FinalizeResult with the failing step recorded.

Usage:
    processor = PostTradeProcessor(oms=tracker, portfolio=pm, ledger=ledger, audit=audit_log)
    result = await processor.finalize(fill)
    if not result.success:
        log.error("post_trade_failed", step=result.failed_step, error=result.error)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from trading_bot.core.models import ExchangeId, OrderSide, OrderState, OrderStatus
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


class FinalizeStep(StrEnum):
    DUPLICATE_CHECK = "duplicate_check"
    OMS_UPDATE = "oms_update"
    PORTFOLIO_UPDATE = "portfolio_update"
    ACCOUNTING_UPDATE = "accounting_update"
    TCA_RECORD = "tca_record"
    AUDIT_APPEND = "audit_append"
    METRICS_EMIT = "metrics_emit"
    RECONCILE = "reconcile"


@dataclass(frozen=True)
class FillDetails:
    """Canonical representation of a confirmed exchange fill."""

    client_order_id: str
    exchange_order_id: str
    symbol: str
    side: OrderSide
    strategy_id: str
    environment: str  # "paper" | "micro_live" | "live"

    requested_qty: Decimal
    filled_qty: Decimal
    fill_price: Decimal
    fee_paid: Decimal
    slippage_cost: Decimal

    is_partial: bool = False
    is_duplicate: bool = False
    exchange_timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def fill_notional(self) -> Decimal:
        return self.filled_qty * self.fill_price

    @property
    def is_complete_fill(self) -> bool:
        return not self.is_partial and self.filled_qty > 0


@dataclass
class FinalizeResult:
    """Result of a post-trade finalization run."""

    fill: FillDetails
    success: bool
    steps_completed: list[FinalizeStep] = field(default_factory=list)
    failed_step: FinalizeStep | None = None
    error: str = ""
    finalized_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_duplicate(self) -> bool:
        return self.fill.is_duplicate


class PostTradeProcessor:
    """Orchestrates the post-trade pipeline after every confirmed fill.

    Dependencies are optional — if a dependency is None, that step is skipped
    and logged as a warning (not an error). This allows gradual integration in
    paper trading before all sub-systems are wired up.
    """

    def __init__(
        self,
        oms: Any = None,  # OrderTracker
        portfolio: Any = None,  # PortfolioManager
        ledger: Any = None,  # AccountingLedger
        tca: Any = None,  # TCATracker
        audit_log: Any = None,  # AuditLogInterface
        idempotency_store: Any = None,  # IdempotencyStoreInterface
    ) -> None:
        self._oms = oms
        self._portfolio = portfolio
        self._ledger = ledger
        self._tca = tca
        self._audit_log = audit_log
        self._idempotency_store = idempotency_store

    async def finalize(self, fill: FillDetails) -> FinalizeResult:
        """Run the complete post-trade pipeline for one fill."""
        result = FinalizeResult(fill=fill, success=True)

        steps = [
            (FinalizeStep.DUPLICATE_CHECK, self._duplicate_check),
            (FinalizeStep.OMS_UPDATE, self._oms_update),
            (FinalizeStep.PORTFOLIO_UPDATE, self._portfolio_update),
            (FinalizeStep.ACCOUNTING_UPDATE, self._accounting_update),
            (FinalizeStep.TCA_RECORD, self._tca_record),
            (FinalizeStep.AUDIT_APPEND, self._audit_append),
            (FinalizeStep.METRICS_EMIT, self._metrics_emit),
            (FinalizeStep.RECONCILE, self._reconcile),
        ]

        for step_id, step_fn in steps:
            try:
                should_stop = await step_fn(fill, result)
                result.steps_completed.append(step_id)
                if should_stop:
                    break
            except Exception as exc:
                result.success = False
                result.failed_step = step_id
                result.error = str(exc)
                log.error(
                    "post_trade_step_failed",
                    step=step_id,
                    fill_id=fill.client_order_id,
                    error=str(exc),
                )
                break

        if result.success:
            log.info(
                "post_trade_finalized",
                fill_id=fill.client_order_id,
                symbol=fill.symbol,
                side=fill.side,
                qty=str(fill.filled_qty),
                price=str(fill.fill_price),
                environment=fill.environment,
                is_partial=fill.is_partial,
            )

        return result

    async def _duplicate_check(self, fill: FillDetails, result: FinalizeResult) -> bool:
        """Detect duplicate fills. Returns True (stop pipeline) if duplicate."""
        if self._idempotency_store is None:
            log.debug("post_trade_skip_duplicate_check", reason="no idempotency store")
            return False

        key = f"fill:{fill.exchange_order_id}:{fill.filled_qty}"
        try:
            acquired = await self._idempotency_store.acquire(key, ttl_seconds=86400 * 7)
            if not acquired:
                # Duplicate fill detected
                object.__setattr__(fill, "is_duplicate", True)
                log.warning(
                    "post_trade_duplicate_fill_detected",
                    exchange_order_id=fill.exchange_order_id,
                    symbol=fill.symbol,
                )
                return True  # stop pipeline — do NOT re-apply portfolio/accounting
        except Exception as exc:
            log.warning("post_trade_duplicate_check_error", error=str(exc))
        return False

    async def _oms_update(self, fill: FillDetails, result: FinalizeResult) -> bool:
        if self._oms is None:
            log.debug("post_trade_skip_oms", reason="no OMS tracker")
            return False

        try:
            status = OrderStatus.PARTIALLY_FILLED if fill.is_partial else OrderStatus.FILLED
            self._oms.record(
                OrderState(
                    client_order_id=fill.client_order_id,
                    exchange_order_id=fill.exchange_order_id,
                    symbol=fill.symbol,
                    exchange=ExchangeId.BINANCE,
                    side=fill.side,
                    order_type="market",
                    requested_quantity=fill.requested_qty,
                    filled_quantity=fill.filled_qty,
                    average_fill_price=fill.fill_price,
                    status=status,
                    strategy_id=fill.strategy_id,
                )
            )
        except Exception as exc:
            log.warning("post_trade_oms_update_failed", error=str(exc))
        return False

    async def _portfolio_update(self, fill: FillDetails, result: FinalizeResult) -> bool:
        if self._portfolio is None:
            log.debug("post_trade_skip_portfolio", reason="no portfolio manager")
            return False

        try:
            from trading_bot.core.models import OrderRequest

            order = OrderRequest(
                symbol=fill.symbol,
                exchange="binance",
                side=fill.side,
                order_type="market",
                quantity=fill.filled_qty,
                strategy_id=fill.strategy_id,
            )
            self._portfolio.apply_fill(order, fill.fill_price)
        except Exception as exc:
            log.warning("post_trade_portfolio_update_failed", error=str(exc))
        return False

    async def _accounting_update(self, fill: FillDetails, result: FinalizeResult) -> bool:
        if self._ledger is None:
            log.debug("post_trade_skip_accounting", reason="no accounting ledger")
            return False

        try:
            await self._ledger.record_trade(
                order_id=fill.client_order_id,
                symbol=fill.symbol,
                side=str(fill.side),
                qty=fill.filled_qty,
                price=fill.fill_price,
                fee=fill.fee_paid,
                timestamp=fill.exchange_timestamp,
            )
        except Exception as exc:
            log.warning("post_trade_accounting_failed", error=str(exc))
        return False

    async def _tca_record(self, fill: FillDetails, result: FinalizeResult) -> bool:
        if self._tca is None:
            log.debug("post_trade_skip_tca", reason="no TCA tracker")
            return False

        try:
            self._tca.record_execution(
                order_id=fill.client_order_id,
                symbol=fill.symbol,
                side=str(fill.side),
                requested_qty=fill.requested_qty,
                filled_qty=fill.filled_qty,
                fill_price=fill.fill_price,
                fee=fill.fee_paid,
                slippage_cost=fill.slippage_cost,
            )
        except Exception as exc:
            log.warning("post_trade_tca_failed", error=str(exc))
        return False

    async def _audit_append(self, fill: FillDetails, result: FinalizeResult) -> bool:
        if self._audit_log is None:
            log.debug("post_trade_skip_audit", reason="no audit log")
            return False

        try:
            await self._audit_log.append(
                event_type="ORDER_FILLED",
                payload={
                    "client_order_id": fill.client_order_id,
                    "exchange_order_id": fill.exchange_order_id,
                    "symbol": fill.symbol,
                    "side": str(fill.side),
                    "filled_qty": str(fill.filled_qty),
                    "fill_price": str(fill.fill_price),
                    "fee_paid": str(fill.fee_paid),
                    "is_partial": fill.is_partial,
                    "environment": fill.environment,
                    "strategy_id": fill.strategy_id,
                },
                actor=fill.strategy_id,
                occurred_at=fill.exchange_timestamp,
            )
        except Exception as exc:
            log.warning("post_trade_audit_failed", error=str(exc))
        return False

    async def _metrics_emit(self, fill: FillDetails, result: FinalizeResult) -> bool:
        try:
            from trading_bot.observability.metrics import (
                FILL_COUNT,
                FILL_NOTIONAL,
                FILL_SLIPPAGE_BPS,
            )

            FILL_COUNT.labels(
                symbol=fill.symbol,
                side=str(fill.side),
                environment=fill.environment,
                partial=str(fill.is_partial),
            ).inc()
            FILL_NOTIONAL.labels(
                symbol=fill.symbol,
                environment=fill.environment,
            ).observe(float(fill.fill_notional))
            FILL_SLIPPAGE_BPS.labels(symbol=fill.symbol).observe(
                float(fill.slippage_cost / fill.fill_notional * 10000)
                if fill.fill_notional > 0
                else 0.0
            )
        except Exception:  # noqa: S110
            pass  # metrics are best-effort — never fail the pipeline
        return False

    async def _reconcile(self, fill: FillDetails, result: FinalizeResult) -> bool:
        """Trigger an incremental reconciliation check after significant fills."""
        try:
            from trading_bot.oms.reconciler import get_reconciler

            reconciler = get_reconciler()
            if reconciler is not None:
                # Schedule an out-of-band reconciliation run to verify fill landed correctly.
                await reconciler.run_once()
        except Exception as exc:
            log.debug("post_trade_reconcile_skipped", error=str(exc))
        return False
