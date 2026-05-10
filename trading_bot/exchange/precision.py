"""Exchange symbol precision and constraint validation.

Before placing any live or micro-live order, ALL constraints must be satisfied.
OrderPrecisionValidator.validate() is the single entry-point; it fails closed
if constraints cannot be loaded.

Constraints are fetched once and cached per symbol per session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from enum import StrEnum


class ValidationFailure(StrEnum):
    BELOW_MIN_QTY = "below_min_qty"
    ABOVE_MAX_QTY = "above_max_qty"
    BELOW_MIN_NOTIONAL = "below_min_notional"
    ABOVE_MAX_NOTIONAL = "above_max_notional"
    LOT_SIZE_VIOLATION = "lot_size_violation"
    TICK_SIZE_VIOLATION = "tick_size_violation"
    INVALID_PRECISION = "invalid_precision"
    CONSTRAINTS_UNAVAILABLE = "constraints_unavailable"


@dataclass(frozen=True)
class SymbolConstraints:
    """Exchange-imposed constraints for a tradable symbol.

    All Decimal values are in base-asset units (qty) or quote-asset units (price).
    """

    symbol: str
    base_asset: str
    quote_asset: str

    # Quantity (lot size) constraints
    min_qty: Decimal
    max_qty: Decimal
    qty_step: Decimal  # lot size step — quantity must be a multiple of this

    # Price (tick size) constraints
    tick_size: Decimal  # price must be a multiple of this

    # Notional value constraints
    min_notional: Decimal  # min_qty * price >= min_notional
    max_notional: Decimal = field(default=Decimal("999_999_999"))

    # Decimal precision for display / API submission
    base_precision: int = 8
    quote_precision: int = 8

    def quantize_qty(self, qty: Decimal) -> Decimal:
        """Round qty DOWN to the nearest valid lot size step."""
        if self.qty_step <= 0:
            return qty
        steps = (qty / self.qty_step).to_integral_value(rounding=ROUND_DOWN)
        return (steps * self.qty_step).quantize(self.qty_step)

    def quantize_price(self, price: Decimal) -> Decimal:
        """Round price DOWN to the nearest valid tick size."""
        if self.tick_size <= 0:
            return price
        ticks = (price / self.tick_size).to_integral_value(rounding=ROUND_DOWN)
        return (ticks * self.tick_size).quantize(self.tick_size)


@dataclass(frozen=True)
class OrderValidationResult:
    approved: bool
    failures: list[ValidationFailure]
    adjusted_qty: Decimal | None  # non-None if qty was quantized to fit step
    adjusted_price: Decimal | None  # non-None if price was quantized to tick
    reason: str

    @classmethod
    def ok(
        cls,
        adjusted_qty: Decimal | None = None,
        adjusted_price: Decimal | None = None,
    ) -> "OrderValidationResult":
        return cls(
            approved=True,
            failures=[],
            adjusted_qty=adjusted_qty,
            adjusted_price=adjusted_price,
            reason="",
        )

    @classmethod
    def fail(cls, failures: list[ValidationFailure], reason: str) -> "OrderValidationResult":
        return cls(
            approved=False,
            failures=failures,
            adjusted_qty=None,
            adjusted_price=None,
            reason=reason,
        )


class OrderPrecisionValidator:
    """Validates and adjusts order qty/price against symbol constraints.

    Quantizes qty and price to the nearest valid step (rounding DOWN to avoid
    accidentally exceeding max notional or position limits). Returns a rejected
    result if constraints cannot be satisfied after quantization.
    """

    def validate(
        self,
        symbol: str,
        qty: Decimal,
        price: Decimal,
        constraints: SymbolConstraints | None,
    ) -> OrderValidationResult:
        if constraints is None:
            return OrderValidationResult.fail(
                [ValidationFailure.CONSTRAINTS_UNAVAILABLE],
                f"symbol constraints unavailable for {symbol} — cannot validate order",
            )

        failures: list[ValidationFailure] = []

        adj_qty = constraints.quantize_qty(qty)
        adj_price = constraints.quantize_price(price)

        # Lot size check (after quantization)
        if adj_qty < constraints.min_qty:
            failures.append(ValidationFailure.BELOW_MIN_QTY)
        if adj_qty > constraints.max_qty:
            failures.append(ValidationFailure.ABOVE_MAX_QTY)

        # Notional check
        notional = adj_qty * adj_price
        if notional < constraints.min_notional:
            failures.append(ValidationFailure.BELOW_MIN_NOTIONAL)
        if notional > constraints.max_notional:
            failures.append(ValidationFailure.ABOVE_MAX_NOTIONAL)

        if failures:
            return OrderValidationResult.fail(
                failures,
                f"order validation failed for {symbol}: {', '.join(f.value for f in failures)} "
                f"(qty={qty}, adj_qty={adj_qty}, price={price}, notional={notional})",
            )

        qty_changed = adj_qty != qty
        price_changed = adj_price != price
        return OrderValidationResult.ok(
            adjusted_qty=adj_qty if qty_changed else None,
            adjusted_price=adj_price if price_changed else None,
        )
