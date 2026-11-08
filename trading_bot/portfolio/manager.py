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
        self._daily_equity_peak = initial_capital
        self._risk_day = datetime.now(UTC).date()

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
        filled_quantity: Decimal | None = None,
        fee_paid: Decimal | None = None,
    ) -> None:
        sym = order.symbol
        qty = filled_quantity if filled_quantity is not None else order.quantity
        fee = fee_paid if fee_paid is not None else qty * fill_price * fee_rate
        if not fee.is_finite() or fee < 0:
            raise ValueError("fill fee must be finite and nonnegative")
        if qty <= 0:
            log.warning(
                "paper_fill_ignored_zero_quantity",
                symbol=sym,
                side=order.side,
                requested_quantity=str(order.quantity),
                filled_quantity=str(qty),
            )
            return

        if order.side == OrderSide.BUY:
            cost = qty * fill_price + fee
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
            proceeds = qty * fill_price - fee
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
                    self.get_snapshot()
                    return
                else:
                    self._qty[sym] = remaining
                    self._current_price[sym] = fill_price

        self.get_snapshot()
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
        for sym in self._qty:
            price = prices.get(sym, prices.get(sym.replace("/", "").upper()))
            if price is not None and price.is_finite() and price > 0:
                self._current_price[sym] = price
        # Observe every tick's high-water mark, even between requested snapshots.
        self.get_snapshot()

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
        today = datetime.now(UTC).date()
        if today != self._risk_day:
            self._risk_day = today
            self._equity_at_day_start = total_equity
            self._daily_equity_peak = total_equity
        self._daily_equity_peak = max(self._daily_equity_peak, total_equity)
        daily_pnl = total_equity - self._equity_at_day_start
        daily_dd = (
            min(Decimal("0"), (total_equity - self._daily_equity_peak) / self._daily_equity_peak)
            if self._daily_equity_peak > 0
            else Decimal("0")
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
        self._cash = Decimal(snap.exact_cash_balance or str(snap.cash_balance))
        equity = Decimal(snap.exact_total_equity or str(snap.total_equity))
        captured_day = datetime.fromisoformat(snap.captured_at).astimezone(UTC).date()
        self._risk_day = datetime.now(UTC).date()
        if (snap.risk_day or captured_day.isoformat()) == self._risk_day.isoformat():
            self._equity_at_day_start = Decimal(
                snap.equity_at_day_start or str(equity - Decimal(str(snap.daily_pnl)))
            )
            self._daily_equity_peak = Decimal(
                snap.daily_equity_peak or str(max(equity, self._equity_at_day_start))
            )
        else:
            self._equity_at_day_start = equity
            self._daily_equity_peak = equity

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
        self._daily_equity_peak = self._equity_at_day_start
        self._risk_day = datetime.now(UTC).date()
        log.info("paper_day_reset", equity=str(self._equity_at_day_start))


def get_portfolio_manager() -> PortfolioManager:
    global _manager
    if _manager is None:
        _manager = PortfolioManager()
    return _manager
