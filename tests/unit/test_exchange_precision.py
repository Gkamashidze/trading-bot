"""Tests for exchange/precision.py — SymbolConstraints + OrderPrecisionValidator."""

from decimal import Decimal

from trading_bot.exchange.precision import (
    OrderPrecisionValidator,
    SymbolConstraints,
    ValidationFailure,
)


def _btc_constraints() -> SymbolConstraints:
    return SymbolConstraints(
        symbol="BTC/USDT",
        base_asset="BTC",
        quote_asset="USDT",
        min_qty=Decimal("0.00001"),
        max_qty=Decimal("9000"),
        qty_step=Decimal("0.00001"),
        tick_size=Decimal("0.01"),
        min_notional=Decimal("10"),
    )


class TestSymbolConstraints:
    def test_quantize_qty_rounds_down(self) -> None:
        c = _btc_constraints()
        qty = Decimal("0.123456789")
        assert c.quantize_qty(qty) == Decimal("0.12345")

    def test_quantize_price_rounds_down(self) -> None:
        c = _btc_constraints()
        price = Decimal("50000.999")
        assert c.quantize_price(price) == Decimal("50000.99")

    def test_quantize_qty_exact_multiple_unchanged(self) -> None:
        c = _btc_constraints()
        assert c.quantize_qty(Decimal("0.00001")) == Decimal("0.00001")

    def test_quantize_zero_step_is_noop(self) -> None:
        c = SymbolConstraints(
            symbol="X",
            base_asset="X",
            quote_asset="Y",
            min_qty=Decimal("0"),
            max_qty=Decimal("1000"),
            qty_step=Decimal("0"),
            tick_size=Decimal("0"),
            min_notional=Decimal("0"),
        )
        assert c.quantize_qty(Decimal("1.23456")) == Decimal("1.23456")


class TestOrderPrecisionValidator:
    def setup_method(self) -> None:
        self.v = OrderPrecisionValidator()
        self.c = _btc_constraints()

    def test_valid_order_passes(self) -> None:
        result = self.v.validate("BTC/USDT", Decimal("0.001"), Decimal("50000"), self.c)
        assert result.approved
        assert not result.failures

    def test_below_min_qty_fails(self) -> None:
        result = self.v.validate("BTC/USDT", Decimal("0.000001"), Decimal("50000"), self.c)
        assert not result.approved
        assert ValidationFailure.BELOW_MIN_QTY in result.failures

    def test_above_max_qty_fails(self) -> None:
        result = self.v.validate("BTC/USDT", Decimal("99999"), Decimal("50000"), self.c)
        assert not result.approved
        assert ValidationFailure.ABOVE_MAX_QTY in result.failures

    def test_below_min_notional_fails(self) -> None:
        result = self.v.validate("BTC/USDT", Decimal("0.00001"), Decimal("100"), self.c)
        assert not result.approved
        assert ValidationFailure.BELOW_MIN_NOTIONAL in result.failures

    def test_constraints_unavailable_fails_closed(self) -> None:
        result = self.v.validate("BTC/USDT", Decimal("0.001"), Decimal("50000"), None)
        assert not result.approved
        assert ValidationFailure.CONSTRAINTS_UNAVAILABLE in result.failures

    def test_qty_adjusted_when_step_misaligned(self) -> None:
        result = self.v.validate("BTC/USDT", Decimal("0.123456789"), Decimal("50000"), self.c)
        assert result.approved
        assert result.adjusted_qty == Decimal("0.12345")

    def test_price_adjusted_when_tick_misaligned(self) -> None:
        result = self.v.validate("BTC/USDT", Decimal("0.001"), Decimal("50000.999"), self.c)
        assert result.approved
        assert result.adjusted_price == Decimal("50000.99")

    def test_no_adjustment_when_exact(self) -> None:
        result = self.v.validate("BTC/USDT", Decimal("0.00100"), Decimal("50000.00"), self.c)
        assert result.approved
        assert result.adjusted_qty is None
        assert result.adjusted_price is None
