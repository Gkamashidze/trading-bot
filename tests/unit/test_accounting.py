"""Tests for Feature #12: Accounting Ledger (FIFO P&L + CSV export)."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

from trading_bot.accounting.ledger import (
    AccountingLedger,
    get_accounting_ledger,
)


def _ledger() -> AccountingLedger:
    return AccountingLedger()


class TestTradeLot:
    def test_buy_lot_recorded(self) -> None:
        ledger = _ledger()
        lot = ledger.record_trade("BTC/USDT", "BUY", 0.1, 50_000.0, fee_usdt=2.5)
        assert lot.side == "BUY"
        assert lot.symbol == "BTC/USDT"
        assert lot.quantity == Decimal("0.1")
        assert lot.price == Decimal("50000.0")
        assert lot.fee_usdt == Decimal("2.5")

    def test_sell_lot_recorded(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 0.1, 50_000.0)
        lot = ledger.record_trade("BTC/USDT", "SELL", 0.1, 55_000.0)
        assert lot.side == "SELL"

    def test_lot_ids_are_unique(self) -> None:
        ledger = _ledger()
        l1 = ledger.record_trade("BTC/USDT", "BUY", 0.1, 50_000.0)
        l2 = ledger.record_trade("BTC/USDT", "BUY", 0.1, 50_000.0)
        assert l1.lot_id != l2.lot_id


class TestFIFOMatching:
    def test_full_match_produces_realized_pnl(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 1.0, 50_000.0)
        ledger.record_trade("BTC/USDT", "SELL", 1.0, 55_000.0)
        assert len(ledger._realized) == 1
        pnl_entry = ledger._realized[0]
        # proceeds=55000, cost=50000, fees=0 → pnl=5000
        assert pnl_entry.pnl == Decimal("5000.00000000")

    def test_pnl_subtracts_fees(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 1.0, 50_000.0, fee_usdt=10.0)
        ledger.record_trade("BTC/USDT", "SELL", 1.0, 55_000.0, fee_usdt=11.0)
        pnl_entry = ledger._realized[0]
        assert pnl_entry.fee_total == Decimal("21.00000000")
        assert pnl_entry.pnl == Decimal("4979.00000000")

    def test_partial_sell_leaves_open_lot(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 1.0, 50_000.0)
        ledger.record_trade("BTC/USDT", "SELL", 0.4, 55_000.0)
        assert len(ledger._realized) == 1
        assert ledger.open_exposure("BTC/USDT") == Decimal("0.6")

    def test_sell_more_than_open_stops_at_zero(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 0.5, 50_000.0)
        ledger.record_trade("BTC/USDT", "SELL", 1.0, 55_000.0)
        # Only 0.5 was available to match
        assert ledger._realized[0].quantity == Decimal("0.5")
        assert ledger.open_exposure("BTC/USDT") == Decimal("0")

    def test_multiple_buy_lots_fifo_order(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 0.5, 50_000.0)  # lot 1 (cheaper)
        ledger.record_trade("BTC/USDT", "BUY", 0.5, 52_000.0)  # lot 2
        ledger.record_trade("BTC/USDT", "SELL", 0.5, 55_000.0)  # should match lot 1
        pnl = ledger._realized[0]
        # FIFO: cost_basis = 0.5 * 50000 = 25000
        assert pnl.cost_basis == Decimal("25000.00000000")

    def test_total_realized_pnl(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 1.0, 50_000.0)
        ledger.record_trade("BTC/USDT", "SELL", 1.0, 55_000.0)
        assert ledger.total_realized_pnl() == Decimal("5000.00000000")

    def test_total_realized_pnl_filtered_by_symbol(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 1.0, 50_000.0)
        ledger.record_trade("BTC/USDT", "SELL", 1.0, 55_000.0)
        ledger.record_trade("ETH/USDT", "BUY", 10.0, 3_000.0)
        ledger.record_trade("ETH/USDT", "SELL", 10.0, 3_500.0)
        btc_pnl = ledger.total_realized_pnl("BTC/USDT")
        eth_pnl = ledger.total_realized_pnl("ETH/USDT")
        assert btc_pnl == Decimal("5000.00000000")
        assert eth_pnl == Decimal("5000.00000000")

    def test_open_exposure_with_no_buys(self) -> None:
        ledger = _ledger()
        assert ledger.open_exposure("BTC/USDT") == Decimal("0")

    def test_buy_only_open_exposure(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 2.0, 50_000.0)
        assert ledger.open_exposure("BTC/USDT") == Decimal("2.0")


class TestCSVExport:
    def test_export_csv_contains_lot_headers(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 0.1, 50_000.0)
        csv_str = ledger.export_csv()
        assert "lot_id" in csv_str
        assert "symbol" in csv_str
        assert "BTC/USDT" in csv_str

    def test_export_csv_contains_realized_pnl_section(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 0.1, 50_000.0)
        ledger.record_trade("BTC/USDT", "SELL", 0.1, 55_000.0)
        csv_str = ledger.export_csv()
        assert "REALIZED P&L" in csv_str
        assert "pnl" in csv_str

    def test_export_csv_is_parseable(self) -> None:
        ledger = _ledger()
        ledger.record_trade("BTC/USDT", "BUY", 0.5, 50_000.0, fee_usdt=1.0)
        ledger.record_trade("BTC/USDT", "SELL", 0.5, 55_000.0, fee_usdt=1.0)
        csv_str = ledger.export_csv()
        rows = list(csv.reader(io.StringIO(csv_str)))
        assert len(rows) > 0

    def test_empty_ledger_export(self) -> None:
        ledger = _ledger()
        csv_str = ledger.export_csv()
        assert "TRADE LOTS" in csv_str
        assert "REALIZED P&L" in csv_str


class TestSingleton:
    def test_singleton_returns_same_instance(self) -> None:
        l1 = get_accounting_ledger()
        l2 = get_accounting_ledger()
        assert l1 is l2
