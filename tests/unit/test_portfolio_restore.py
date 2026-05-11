"""Tests for crash/restart portfolio recovery.

Covers:
- PortfolioManager.restore_from_snapshot() — state applied correctly
- portfolio/rebuilder.py — snapshot + DB fill replay
- CircuitBreaker.restore_state() — tier persisted across restart
- Backwards-compatible snapshot without opened_at / strategy_id
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from trading_bot.disaster_recovery.snapshotter import StateSnapshot
from trading_bot.portfolio.manager import PortfolioManager
from trading_bot.safety.circuit_breaker import CircuitBreaker

# ── Helpers ──────────────────────────────────────────────────────────────────


def _snap(
    cash: float = 8_000.0,
    equity: float = 10_000.0,
    positions: list[dict] | None = None,
    cb_tier: int = 0,
    cb_tripped_at: str | None = None,
) -> StateSnapshot:
    if positions is None:
        positions = [
            {
                "symbol": "BTC/USDT",
                "qty": 0.04,
                "avg_cost": 50_000.0,
                "current_price": 50_000.0,
                "opened_at": "2026-05-11T10:00:00+00:00",
                "strategy_id": "sma_cross",
            }
        ]
    return StateSnapshot(
        captured_at="2026-05-11T10:00:00+00:00",
        total_equity=equity,
        cash_balance=cash,
        daily_pnl=0.0,
        daily_drawdown_pct=0.0,
        position_count=len(positions),
        positions=positions,
        cb_tier=cb_tier,
        cb_peak_tier=cb_tier,
        cb_tripped_at=cb_tripped_at,
        manager_type="paper",
    )


def _mock_pool(rows: list[dict] | None = None) -> MagicMock:
    if rows is None:
        rows = []
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=rows)
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool


# ── PortfolioManager.restore_from_snapshot ────────────────────────────────────


class TestPortfolioManagerRestoreFromSnapshot:
    def test_cash_set_correctly(self) -> None:
        pm = PortfolioManager(initial_capital=Decimal("10000"))
        pm.restore_from_snapshot(_snap(cash=7_500.0))
        assert pm._cash == Decimal("7500.0")

    def test_position_qty_set(self) -> None:
        pm = PortfolioManager()
        pm.restore_from_snapshot(_snap())
        assert pm._qty["BTC/USDT"] == Decimal("0.04")

    def test_position_avg_cost_set(self) -> None:
        pm = PortfolioManager()
        pm.restore_from_snapshot(_snap())
        assert pm._avg_cost["BTC/USDT"] == Decimal("50000.0")

    def test_position_current_price_set(self) -> None:
        pm = PortfolioManager()
        pm.restore_from_snapshot(_snap())
        assert pm._current_price["BTC/USDT"] == Decimal("50000.0")

    def test_position_strategy_id_set(self) -> None:
        pm = PortfolioManager()
        pm.restore_from_snapshot(_snap())
        assert pm._strategy_id["BTC/USDT"] == "sma_cross"

    def test_position_opened_at_parsed(self) -> None:
        pm = PortfolioManager()
        pm.restore_from_snapshot(_snap())
        assert pm._opened_at["BTC/USDT"].year == 2026

    def test_previous_positions_cleared(self) -> None:
        pm = PortfolioManager()
        # Prime with a stale position
        pm._qty["ETH/USDT"] = Decimal("1.0")
        pm._avg_cost["ETH/USDT"] = Decimal("3000")
        pm._current_price["ETH/USDT"] = Decimal("3000")
        pm._opened_at["ETH/USDT"] = datetime.now(UTC)
        pm._strategy_id["ETH/USDT"] = "rsi"

        pm.restore_from_snapshot(_snap())

        assert "ETH/USDT" not in pm._qty  # stale position cleared
        assert "BTC/USDT" in pm._qty  # new snapshot position applied

    def test_no_positions_restores_empty(self) -> None:
        pm = PortfolioManager()
        pm._qty["BTC/USDT"] = Decimal("0.1")
        pm.restore_from_snapshot(_snap(positions=[]))
        assert len(pm._qty) == 0

    def test_backwards_compat_missing_opened_at(self) -> None:
        """Old snapshots without opened_at should not crash."""
        pm = PortfolioManager()
        snap = _snap(
            positions=[
                {"symbol": "BTC/USDT", "qty": 0.01, "avg_cost": 50000.0, "current_price": 50000.0}
            ]
        )
        pm.restore_from_snapshot(snap)  # must not raise
        assert "BTC/USDT" in pm._qty
        assert isinstance(pm._opened_at["BTC/USDT"], datetime)

    def test_backwards_compat_missing_strategy_id(self) -> None:
        pm = PortfolioManager()
        snap = _snap(
            positions=[
                {
                    "symbol": "BTC/USDT",
                    "qty": 0.01,
                    "avg_cost": 50000.0,
                    "current_price": 50000.0,
                    "opened_at": "2026-05-11T10:00:00+00:00",
                }
            ]
        )
        pm.restore_from_snapshot(snap)
        assert pm._strategy_id["BTC/USDT"] == ""

    def test_equity_at_day_start_updated(self) -> None:
        pm = PortfolioManager()
        pm.restore_from_snapshot(_snap(equity=11_000.0))
        assert pm._equity_at_day_start == Decimal("11000.0")


# ── CircuitBreaker.restore_state ─────────────────────────────────────────────


class TestCircuitBreakerRestoreState:
    def test_tier_restored(self) -> None:
        cb = CircuitBreaker()
        cb.restore_state(tier=2, peak_tier=2, tripped_at=None)
        assert cb.current_tier == 2

    def test_peak_tier_restored(self) -> None:
        cb = CircuitBreaker()
        cb.restore_state(tier=1, peak_tier=3, tripped_at=None)
        assert cb.peak_tier_today == 3

    def test_tripped_at_none(self) -> None:
        cb = CircuitBreaker()
        cb.restore_state(tier=0, peak_tier=0, tripped_at=None)
        assert cb.tripped_at is None

    def test_tripped_at_parsed(self) -> None:
        cb = CircuitBreaker()
        cb.restore_state(tier=3, peak_tier=3, tripped_at="2026-05-11T09:00:00+00:00")
        assert cb.tripped_at is not None
        assert cb.tripped_at.year == 2026

    def test_tier_3_halts_trading(self) -> None:
        cb = CircuitBreaker()
        cb.restore_state(tier=3, peak_tier=3, tripped_at="2026-05-11T09:00:00+00:00")
        assert not cb.is_trading_allowed()

    def test_tier_0_allows_trading(self) -> None:
        cb = CircuitBreaker()
        cb.restore_state(tier=0, peak_tier=0, tripped_at=None)
        assert cb.is_trading_allowed()


# ── portfolio/rebuilder.py ────────────────────────────────────────────────────


class TestRebuildPortfolio:
    async def test_cold_start_no_fills_empty_portfolio(self) -> None:
        pool = _mock_pool(rows=[])
        pm = PortfolioManager(initial_capital=Decimal("10000"))

        with (
            patch("trading_bot.portfolio.rebuilder.restore_latest_snapshot", return_value=None),
            patch("trading_bot.portfolio.rebuilder.get_portfolio_manager", return_value=pm),
        ):
            from trading_bot.portfolio.rebuilder import rebuild_portfolio

            snap, replayed = await rebuild_portfolio(pool)

        assert snap is None
        assert replayed == 0
        assert pm._cash == Decimal("10000")

    async def test_snapshot_applied_then_fills_replayed(self) -> None:
        import trading_bot.portfolio.rebuilder as rb_mod

        snapshot = _snap(cash=8_000.0, positions=[])
        fill_row = {
            "symbol": "BTC/USDT",
            "side": "buy",
            "strategy_id": "sma_cross",
            "filled_qty": 0.04,
            "fill_price": 50_000.0,
            "created_at": datetime(2026, 5, 11, 10, 30, tzinfo=UTC),
        }
        pool = _mock_pool(rows=[fill_row])
        pm = PortfolioManager(initial_capital=Decimal("10000"))

        with (
            patch.object(rb_mod, "restore_latest_snapshot", return_value=snapshot),
            patch.object(rb_mod, "get_portfolio_manager", return_value=pm),
        ):
            snap_out, replayed = await rb_mod.rebuild_portfolio(pool)

        assert snap_out is snapshot
        assert replayed == 1
        assert "BTC/USDT" in pm._qty

    async def test_db_failure_does_not_crash(self) -> None:
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(side_effect=Exception("DB down"))
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        pm = PortfolioManager(initial_capital=Decimal("10000"))

        with (
            patch("trading_bot.portfolio.rebuilder.restore_latest_snapshot", return_value=None),
            patch("trading_bot.portfolio.rebuilder.get_portfolio_manager", return_value=pm),
        ):
            from trading_bot.portfolio.rebuilder import rebuild_portfolio

            _snap_out, replayed = await rebuild_portfolio(pool)

        assert replayed == 0  # graceful degradation
        assert pm._cash == Decimal("10000")  # unchanged


# ── Scenario: crash immediately after fill, before next snapshot ──────────────


class TestCrashAfterFillScenario:
    """Bot fills a BUY at 10:01, snapshot was at 10:00, next snapshot at 11:00.
    Bot crashes at 10:02.  On restart, snapshot is 10:00 (1-min stale).
    DB fill row for 10:01 must be replayed to recover the position.
    """

    async def test_position_recovered_via_db_replay(self) -> None:
        import trading_bot.portfolio.rebuilder as rb_mod

        snapshot = _snap(cash=10_000.0, positions=[])  # no position in snapshot (crash was before)
        fill_row = {
            "symbol": "BTC/USDT",
            "side": "buy",
            "strategy_id": "sma_cross",
            "filled_qty": 0.04,
            "fill_price": 50_000.0,
            "created_at": datetime(2026, 5, 11, 10, 1, tzinfo=UTC),  # after snapshot
        }
        pool = _mock_pool(rows=[fill_row])
        pm = PortfolioManager(initial_capital=Decimal("10000"))

        with (
            patch.object(rb_mod, "restore_latest_snapshot", return_value=snapshot),
            patch.object(rb_mod, "get_portfolio_manager", return_value=pm),
        ):
            _, replayed = await rb_mod.rebuild_portfolio(pool)

        assert replayed == 1
        assert "BTC/USDT" in pm._qty
        assert pm._qty["BTC/USDT"] > Decimal("0")

    async def test_fill_before_snapshot_not_double_counted(self) -> None:
        """Fill at 09:30 is already in snapshot cash; DB query filters it out via since_dt."""
        import trading_bot.portfolio.rebuilder as rb_mod

        snapshot = _snap(
            cash=7_980.0,  # already reflects 09:30 BUY
            positions=[
                {
                    "symbol": "BTC/USDT",
                    "qty": 0.04,
                    "avg_cost": 50_000.0,
                    "current_price": 50_000.0,
                    "opened_at": "2026-05-11T09:30:00+00:00",
                    "strategy_id": "sma_cross",
                }
            ],
        )
        # No rows returned (DB query uses since > snapshot.captured_at = 10:00)
        pool = _mock_pool(rows=[])
        pm = PortfolioManager(initial_capital=Decimal("10000"))

        with (
            patch.object(rb_mod, "restore_latest_snapshot", return_value=snapshot),
            patch.object(rb_mod, "get_portfolio_manager", return_value=pm),
        ):
            _, replayed = await rb_mod.rebuild_portfolio(pool)

        assert replayed == 0
        # Position exactly as in snapshot — no double-counting
        assert pm._qty["BTC/USDT"] == Decimal("0.04")
        assert pm._cash == Decimal("7980.0")
