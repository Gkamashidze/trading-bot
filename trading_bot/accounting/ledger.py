"""Tax, Accounting, and Export Layer — Feature #12.

Tracks trade lots and realizes PnL using FIFO matching. Produces CSV
exports suitable for accountants and tax preparation tools.

Usage:
    ledger = get_accounting_ledger()
    lot = ledger.record_trade("BTC/USDT", "BUY", qty=0.1, price=50000.0, fee=2.50)
    realized = ledger.record_trade("BTC/USDT", "SELL", qty=0.1, price=55000.0, fee=2.75)
    csv_str = ledger.export_csv()
"""

from __future__ import annotations

import csv
import io
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_ZERO = Decimal("0")
_PREC = Decimal("0.00000001")


# ---------------------------------------------------------------------------
# Immutable records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeLot:
    """A single buy or sell lot as recorded at execution time."""

    lot_id: str
    symbol: str
    side: str  # "BUY" | "SELL"
    quantity: Decimal
    price: Decimal  # average fill price
    fee_usdt: Decimal
    trade_time: datetime
    order_id: str = ""


@dataclass(frozen=True)
class RealizedPnL:
    """Realized P&L entry produced when a SELL lot is matched against a BUY lot."""

    entry_id: str
    symbol: str
    quantity: Decimal  # quantity matched
    buy_lot_id: str
    sell_lot_id: str
    proceeds: Decimal  # sell qty * sell price
    cost_basis: Decimal  # buy qty * buy price
    fee_total: Decimal  # buy fee + sell fee (pro-rated for partial)
    pnl: Decimal  # proceeds - cost_basis - fee_total
    trade_time: datetime  # time of the sell


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


@dataclass
class AccountingLedger:
    """FIFO-matched accounting ledger for all symbols.

    Thread-safe under the GIL for single-threaded async use.
    """

    _open_lots: dict[str, deque[TradeLot]] = field(default_factory=dict)
    _all_lots: list[TradeLot] = field(default_factory=list)
    _realized: list[RealizedPnL] = field(default_factory=list)

    def record_trade(
        self,
        symbol: str,
        side: str,
        quantity: float | Decimal,
        price: float | Decimal,
        fee_usdt: float | Decimal = 0.0,
        order_id: str = "",
        trade_time: datetime | None = None,
    ) -> TradeLot:
        """Record a BUY or SELL and run FIFO matching for SELLs."""
        qty = Decimal(str(quantity)).quantize(_PREC, rounding=ROUND_HALF_UP)
        px = Decimal(str(price)).quantize(_PREC, rounding=ROUND_HALF_UP)
        fee = Decimal(str(fee_usdt)).quantize(_PREC, rounding=ROUND_HALF_UP)
        ts = trade_time or datetime.now(UTC)

        lot = TradeLot(
            lot_id=str(uuid.uuid4()),
            symbol=symbol,
            side=side.upper(),
            quantity=qty,
            price=px,
            fee_usdt=fee,
            trade_time=ts,
            order_id=order_id,
        )
        self._all_lots.append(lot)

        if side.upper() == "BUY":
            if symbol not in self._open_lots:
                self._open_lots[symbol] = deque()
            self._open_lots[symbol].append(lot)
            log.info("accounting_buy_lot", symbol=symbol, qty=str(qty), price=str(px))

        elif side.upper() == "SELL":
            self._match_sell(lot)

        return lot

    def _match_sell(self, sell_lot: TradeLot) -> None:
        """FIFO-match a sell lot against open buy lots, creating RealizedPnL entries."""
        symbol = sell_lot.symbol
        remaining_sell = sell_lot.quantity
        open_q = self._open_lots.get(symbol, deque())

        while remaining_sell > _ZERO and open_q:
            buy_lot = open_q[0]
            match_qty = min(remaining_sell, buy_lot.quantity)

            # pro-rate fees by fraction of lot consumed
            buy_fee_share = (buy_lot.fee_usdt * (match_qty / buy_lot.quantity)).quantize(
                _PREC, rounding=ROUND_HALF_UP
            )
            sell_fee_share = (sell_lot.fee_usdt * (match_qty / sell_lot.quantity)).quantize(
                _PREC, rounding=ROUND_HALF_UP
            )

            proceeds = (match_qty * sell_lot.price).quantize(_PREC, rounding=ROUND_HALF_UP)
            cost = (match_qty * buy_lot.price).quantize(_PREC, rounding=ROUND_HALF_UP)
            fee_total = buy_fee_share + sell_fee_share
            pnl = proceeds - cost - fee_total

            entry = RealizedPnL(
                entry_id=str(uuid.uuid4()),
                symbol=symbol,
                quantity=match_qty,
                buy_lot_id=buy_lot.lot_id,
                sell_lot_id=sell_lot.lot_id,
                proceeds=proceeds,
                cost_basis=cost,
                fee_total=fee_total,
                pnl=pnl,
                trade_time=sell_lot.trade_time,
            )
            self._realized.append(entry)
            log.info(
                "accounting_pnl_realized",
                symbol=symbol,
                qty=str(match_qty),
                pnl=str(pnl),
            )

            remaining_sell -= match_qty
            if match_qty == buy_lot.quantity:
                open_q.popleft()
            else:
                # Partial consumption: replace lot with reduced quantity
                reduced = TradeLot(
                    lot_id=buy_lot.lot_id,
                    symbol=buy_lot.symbol,
                    side=buy_lot.side,
                    quantity=(buy_lot.quantity - match_qty).quantize(_PREC, rounding=ROUND_HALF_UP),
                    price=buy_lot.price,
                    fee_usdt=(buy_lot.fee_usdt - buy_fee_share).quantize(
                        _PREC, rounding=ROUND_HALF_UP
                    ),
                    trade_time=buy_lot.trade_time,
                    order_id=buy_lot.order_id,
                )
                open_q[0] = reduced

    def realized_for_sell(self, sell_lot_id: str) -> tuple[Decimal, Decimal] | None:
        """Return (total_pnl, total_cost_basis) realized by a sell lot, or None.

        A single SELL may FIFO-match several open BUY lots, producing multiple
        RealizedPnL entries — this aggregates them. Used by the evidence recorder
        to populate realized_pnl / cost_basis on a completed round-trip.
        """
        entries = [e for e in self._realized if e.sell_lot_id == sell_lot_id]
        if not entries:
            return None
        total_pnl = sum((e.pnl for e in entries), _ZERO)
        total_cost = sum((e.cost_basis for e in entries), _ZERO)
        return total_pnl, total_cost

    def total_realized_pnl(self, symbol: str | None = None) -> Decimal:
        entries = (
            self._realized if symbol is None else [e for e in self._realized if e.symbol == symbol]
        )
        return sum((e.pnl for e in entries), _ZERO)

    def open_exposure(self, symbol: str) -> Decimal:
        """Total open quantity for a symbol (FIFO remainder)."""
        open_q = self._open_lots.get(symbol, deque())
        return sum((lot.quantity for lot in open_q), _ZERO)

    def export_csv(self) -> str:
        """Return all lots and realized P&L as a UTF-8 CSV string."""
        buf = io.StringIO()
        writer = csv.writer(buf)

        writer.writerow(["# TRADE LOTS"])
        writer.writerow(
            [
                "lot_id",
                "symbol",
                "side",
                "quantity",
                "price",
                "fee_usdt",
                "trade_time",
                "order_id",
            ]
        )
        for lot in self._all_lots:
            writer.writerow(
                [
                    lot.lot_id,
                    lot.symbol,
                    lot.side,
                    str(lot.quantity),
                    str(lot.price),
                    str(lot.fee_usdt),
                    lot.trade_time.isoformat(),
                    lot.order_id,
                ]
            )

        writer.writerow([])
        writer.writerow(["# REALIZED P&L"])
        writer.writerow(
            [
                "entry_id",
                "symbol",
                "quantity",
                "buy_lot_id",
                "sell_lot_id",
                "proceeds",
                "cost_basis",
                "fee_total",
                "pnl",
                "trade_time",
            ]
        )
        for e in self._realized:
            writer.writerow(
                [
                    e.entry_id,
                    e.symbol,
                    str(e.quantity),
                    e.buy_lot_id,
                    e.sell_lot_id,
                    str(e.proceeds),
                    str(e.cost_basis),
                    str(e.fee_total),
                    str(e.pnl),
                    e.trade_time.isoformat(),
                ]
            )

        return buf.getvalue()


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_ledger: AccountingLedger | None = None


def get_accounting_ledger() -> AccountingLedger:
    global _ledger
    if _ledger is None:
        _ledger = AccountingLedger()
    return _ledger
