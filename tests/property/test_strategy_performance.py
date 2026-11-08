"""Accounting properties for marked strategy evidence and promotion gates."""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from trading_bot.evidence.performance import reconstruct_strategy_equity
from trading_bot.promotion.pipeline import PromotionTier, StrategyMetrics, StrategyPromotion


def _fill(side: str, price: Decimal, qty: Decimal, fee: Decimal) -> dict:
    return {
        "strategy_id": "sma",
        "symbol": "BTC/USDT",
        "side": side,
        "quantity": qty,
        "fill_price": price,
        "fee_paid": fee,
    }


@given(
    price=st.decimals(min_value="1", max_value="100000", places=2),
    quantity=st.decimals(min_value="0.001", max_value="1", places=3),
    fee=st.decimals(min_value="0", max_value="10", places=2),
)
def test_flat_round_trip_loses_exactly_fees(
    price: Decimal, quantity: Decimal, fee: Decimal
) -> None:
    capital = Decimal("1000000")
    books = reconstruct_strategy_equity(
        [_fill("buy", price, quantity, fee), _fill("sell", price, quantity, fee)], {}, capital
    )
    assert books["sma"]["complete"]
    assert Decimal(books["sma"]["equity"]) == capital - fee * 2


def test_missing_market_mark_and_cross_strategy_inventory_are_not_valid_evidence() -> None:
    book = reconstruct_strategy_equity(
        [_fill("buy", Decimal(100), Decimal(1), Decimal(1))], {}, Decimal(1000)
    )
    assert not book["sma"]["complete"]
    book = reconstruct_strategy_equity(
        [_fill("sell", Decimal(100), Decimal(1), Decimal(1))], {}, Decimal(1000)
    )
    assert not book["sma"]["complete"]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_metrics_cannot_promote(value: float) -> None:
    metrics = StrategyMetrics(100, value, 0.01, 0.8, 200)
    assert not StrategyPromotion("sma", PromotionTier.PAPER).can_advance(metrics)[0]
