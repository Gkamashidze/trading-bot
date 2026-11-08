"""Real ticks and restart recovery must preserve the portfolio's risk information."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from trading_bot.core.models import ExchangeId, OrderRequest, OrderSide, OrderType, PriceTick
from trading_bot.disaster_recovery.snapshotter import (
    capture_snapshot,
    restore_latest_snapshot,
    save_snapshot,
)
from trading_bot.portfolio import manager
from trading_bot.websocket.price_cache import PriceCache


def _portfolio() -> manager.PortfolioManager:
    portfolio = manager.PortfolioManager(Decimal("1000"))
    portfolio.apply_fill(
        OrderRequest(
            symbol="BTC/USDT",
            exchange=ExchangeId.BINANCE,
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("5"),
            strategy_id="test",
        ),
        Decimal("100"),
        fee_paid=Decimal("0"),
    )
    return portfolio


def _tick(price: str, at: datetime | None = None) -> PriceTick:
    return PriceTick(
        symbol="BTCUSDT",
        price=Decimal(price),
        open_24h=Decimal("100"),
        high_24h=Decimal("200"),
        low_24h=Decimal("1"),
        volume_24h=Decimal("100"),
        timestamp=at or datetime.now(UTC),
    )


async def test_fresh_market_tick_revalues_existing_inventory(monkeypatch) -> None:
    portfolio = _portfolio()
    monkeypatch.setattr(manager, "_manager", portfolio)
    await PriceCache().update(_tick("50"))
    snapshot = portfolio.get_snapshot()
    assert snapshot.total_equity == Decimal("750")
    assert snapshot.daily_pnl == Decimal("-250")
    assert snapshot.daily_drawdown_pct == Decimal("-0.25")


async def test_out_of_order_tick_cannot_overwrite_a_newer_valuation(monkeypatch) -> None:
    portfolio = _portfolio()
    monkeypatch.setattr(manager, "_manager", portfolio)
    cache = PriceCache()
    now = datetime.now(UTC)
    await cache.update(_tick("80", now))
    await cache.update(_tick("200", now - timedelta(seconds=1)))
    assert portfolio.get_snapshot().total_equity == Decimal("900")


def test_gains_are_not_drawdowns_and_retracement_uses_daily_peak() -> None:
    portfolio = _portfolio()
    portfolio.update_prices({"BTC/USDT": Decimal("200")})
    assert portfolio.get_snapshot().daily_drawdown_pct == 0
    portfolio.update_prices({"BTC/USDT": Decimal("160")})
    snapshot = portfolio.get_snapshot()
    assert snapshot.daily_pnl == Decimal("300")
    assert snapshot.daily_drawdown_pct == Decimal("-200") / Decimal("1500")
    portfolio.reset_day()
    assert portfolio.get_snapshot().daily_drawdown_pct == 0
    assert portfolio.get_snapshot().daily_pnl == 0


def test_same_day_snapshot_round_trip_keeps_exact_risk_baseline(monkeypatch, tmp_path) -> None:
    portfolio = _portfolio()
    monkeypatch.setattr(manager, "_manager", portfolio)
    portfolio.update_prices({"BTC/USDT": Decimal("200.1234567890123")})
    portfolio.update_prices({"BTC/USDT": Decimal("160.1234567890123")})
    expected = portfolio.get_snapshot()
    save_snapshot(capture_snapshot(), tmp_path)
    snapshot = restore_latest_snapshot(tmp_path)
    assert snapshot is not None
    restored = manager.PortfolioManager()
    restored.restore_from_snapshot(snapshot)
    actual = restored.get_snapshot()
    assert actual.total_equity == expected.total_equity
    assert actual.daily_pnl == expected.daily_pnl
    assert actual.daily_drawdown_pct == expected.daily_drawdown_pct


def test_next_day_restore_uses_a_new_daily_baseline(monkeypatch) -> None:
    portfolio = _portfolio()
    monkeypatch.setattr(manager, "_manager", portfolio)
    portfolio.update_prices({"BTC/USDT": Decimal("80")})
    snapshot = capture_snapshot()
    yesterday = datetime.now(UTC) - timedelta(days=1)
    snapshot = replace(
        snapshot, risk_day=yesterday.date().isoformat(), captured_at=yesterday.isoformat()
    )
    restored = manager.PortfolioManager()
    restored.restore_from_snapshot(snapshot)
    assert restored.get_snapshot().daily_pnl == 0
    assert restored.get_snapshot().daily_drawdown_pct == 0


def test_corrupt_newest_snapshot_falls_back_without_rewriting_history(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(manager, "_manager", _portfolio())
    expected = capture_snapshot()
    save_snapshot(expected, tmp_path)
    corrupt = tmp_path / "state_99999999_corrupt.json"
    corrupt.write_text('{"unfinished":')
    assert restore_latest_snapshot(tmp_path) == expected
    assert corrupt.read_text() == '{"unfinished":'


@given(st.decimals(min_value="0.01", max_value="1000", places=4))
def test_marked_drawdown_is_never_positive(price: Decimal) -> None:
    portfolio = _portfolio()
    portfolio.update_prices({"BTC/USDT": price})
    snapshot = portfolio.get_snapshot()
    assert snapshot.total_equity == Decimal("500") + Decimal("5") * price
    assert Decimal("-1") <= snapshot.daily_drawdown_pct <= 0
