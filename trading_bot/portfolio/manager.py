"""In-memory paper portfolio manager.

Tracks positions, cash, and daily P&L for paper trading.
Singleton via get_portfolio_manager().

All mutations happen in the asyncio event loop (single-threaded), so no
locking is required. Reads are safe from any context.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading_bot.disaster_recovery.snapshotter import StateSnapshot

from trading_bot.core.models import (
    AssetClass,
    ExchangeId,
    OrderRequest,
    OrderSide,
    PortfolioSnapshot,
    Position,
)
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_INITIAL_CAPITAL = Decimal(os.environ.get("PAPER_CAPITAL", "10000"))
_manager: PortfolioManager | None = None


class PortfolioManager:
    def __init__(self, initial_capital: Decimal = _INITIAL_CAPITAL) -> None:
        self._cash = initial_capital
        self._initial_capital = initial_capital
        self._equity_at_day_start = initial_capital

        # Per-symbol position state (parallel dicts for simplicity)
        self._qty: dict[str, Decimal] = {}
        self._avg_cost: dict[str, Decimal] = {}
        self._current_price: dict[str, Decimal] = {}
        self._opened_at: dict[str, datetime] = {}
        self._strategy_id: dict[str, str] = {}

    def apply_fill(
        self,
        order: OrderRequest,
        fill_price: Decimal,
        fee_rate: Decimal = Decimal("0.001"),
    ) -> None:
        sym = order.symbol
        qty = order.quantity

        if order.side == OrderSide.BUY:
            cost = qty * fill_price * (1 + fee_rate)
            self._cash -= cost

            if sym in self._qty:
                old_qty = self._qty[sym]
                old_avg = self._avg_cost[sym]
                new_qty = old_qty + qty
                self._avg_cost[sym] = (old_avg * old_qty + fill_price * qty) / new_qty
                self._qty[sym] = new_qty
            else:
                self._qty[sym] = qty
                self._avg_cost[sym] = fill_price
                self._current_price[sym] = fill_price
                self._opened_at[sym] = datetime.now(UTC)
                self._strategy_id[sym] = order.strategy_id

            self._current_price[sym] = fill_price

        elif order.side == OrderSide.SELL:
            proceeds = qty * fill_price * (1 - fee_rate)
            self._cash += proceeds

            if sym in self._qty:
                remaining = self._qty[sym] - qty
                if remaining <= Decimal("0.0000001"):
                    for d in (
                        self._qty,
                        self._avg_cost,
                        self._current_price,
                        self._opened_at,
                        self._strategy_id,
                    ):
                        d.pop(sym, None)
                    log.info(
                        "paper_position_closed",
                        symbol=sym,
                        fill_price=str(fill_price),
                        cash=str(self._cash),
                    )
                    return
                else:
                    self._qty[sym] = remaining
                    self._current_price[sym] = fill_price

        log.info(
            "paper_fill",
            symbol=sym,
            side=order.side,
            qty=str(qty),
            price=str(fill_price),
            cash=str(self._cash),
        )

    def update_prices(self, prices: dict[str, Decimal]) -> None:
        """Refresh mark-to-market prices for open positions."""
        for sym, price in prices.items():
            if sym in self._qty:
                self._current_price[sym] = price

    def get_snapshot(self) -> PortfolioSnapshot:
        positions: list[Position] = []
        total_pos_value = Decimal("0")

        for sym, qty in self._qty.items():
            price = self._current_price.get(sym, self._avg_cost.get(sym, Decimal("0")))
            pos = Position(
                symbol=sym,
                exchange=ExchangeId.BINANCE,
                asset_class=AssetClass.CRYPTO,
                quantity=qty,
                average_cost=self._avg_cost[sym],
                current_price=price,
                opened_at=self._opened_at[sym],
                strategy_id=self._strategy_id.get(sym, ""),
            )
            positions.append(pos)
            total_pos_value += qty * price

        total_equity = self._cash + total_pos_value
        daily_pnl = total_equity - self._equity_at_day_start
        daily_dd = (
            daily_pnl / self._equity_at_day_start if self._equity_at_day_start > 0 else Decimal("0")
        )
        return PortfolioSnapshot(
            cash_balance=self._cash,
            positions=positions,
            total_equity=total_equity,
            daily_pnl=daily_pnl,
            daily_drawdown_pct=daily_dd,
        )

    def restore_from_snapshot(self, snap: StateSnapshot) -> None:
        """Replace all in-memory state from a disaster-recovery snapshot.

        Backwards-compatible: old snapshots without opened_at / strategy_id
        use safe defaults (now() and empty string).
        """
        self._cash = Decimal(str(snap.cash_balance))
        self._equity_at_day_start = Decimal(str(snap.total_equity))

        self._qty.clear()
        self._avg_cost.clear()
        self._current_price.clear()
        self._opened_at.clear()
        self._strategy_id.clear()

        for pos in snap.positions:
            sym = str(pos["symbol"])
            self._qty[sym] = Decimal(str(pos["qty"]))
            self._avg_cost[sym] = Decimal(str(pos["avg_cost"]))
            self._current_price[sym] = Decimal(str(pos["current_price"]))

            raw_opened = pos.get("opened_at")
            if raw_opened:
                try:
                    self._opened_at[sym] = datetime.fromisoformat(str(raw_opened))
                except ValueError:
                    self._opened_at[sym] = datetime.now(UTC)
            else:
                self._opened_at[sym] = datetime.now(UTC)

            self._strategy_id[sym] = str(pos.get("strategy_id", ""))

        log.info(
            "portfolio_restored_from_snapshot",
            cash=str(self._cash),
            positions=len(self._qty),
            captured_at=snap.captured_at,
        )

    def reset_day(self) -> None:
        """Call at UTC midnight to reset daily P&L baseline."""
        self._equity_at_day_start = self.get_snapshot().total_equity
        log.info("paper_day_reset", equity=str(self._equity_at_day_start))


def get_portfolio_manager() -> PortfolioManager:
    global _manager
    if _manager is None:
        _manager = PortfolioManager()
    return _manager
