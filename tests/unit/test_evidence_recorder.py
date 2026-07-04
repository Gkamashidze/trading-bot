"""Unit tests for the execution → evidence bridge (Gate 0 capture).

Covers:
- record_fill_evidence writes a TCA + accounting record when a session is active
- realized_pnl / cost_basis populated on SELL round-trips
- no-op when no active session or store not initialised
- evidence write failures are swallowed (never break trading)
- record_signal_evidence writes one snapshot per result
- AccountingLedger.realized_for_sell aggregation
- EvidenceStore.count_round_trips query
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.accounting.ledger import AccountingLedger
from trading_bot.evidence import recorder
from trading_bot.evidence.store import EvidenceStore
from trading_bot.strategies.base import StrategyResult

_SESSION = uuid.uuid4()


def _mock_store() -> MagicMock:
    store = MagicMock()
    store.insert_tca_record = AsyncMock(return_value=True)
    store.insert_accounting_record = AsyncMock(return_value=True)
    store.insert_signal_snapshot = AsyncMock(return_value=True)
    return store


def _fill_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "order_id": "ord-1",
        "symbol": "BTC/USDT",
        "strategy_id": "sma_crossover",
        "side": "BUY",
        "signal_price": 50000,
        "fill_price": 50010,
        "quantity": "0.01",
        "fee_paid": 0.5,
        "slippage_pct": 0.0002,
        "slippage_usdt": 0.1,
        "latency_ms": 12.5,
        "quality_score": "excellent",
        "outcome": "filled",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# record_fill_evidence
# ---------------------------------------------------------------------------


class TestRecordFillEvidence:
    @pytest.mark.asyncio
    async def test_writes_tca_and_accounting_when_session_active(self) -> None:
        store = _mock_store()
        with (
            patch.object(recorder, "get_current_session_id", return_value=_SESSION),
            patch.object(recorder, "get_evidence_store", return_value=store),
        ):
            await recorder.record_fill_evidence(**_fill_kwargs())

        store.insert_tca_record.assert_awaited_once()
        store.insert_accounting_record.assert_awaited_once()
        tca = store.insert_tca_record.await_args.args[0]
        assert tca.session_id == _SESSION
        assert tca.order_id == "ord-1"
        assert tca.idempotency_key == "tca:ord-1"
        assert tca.signal_price == Decimal("50000")
        assert tca.quantity == Decimal("0.01")

    @pytest.mark.asyncio
    async def test_populates_realized_pnl_on_sell_round_trip(self) -> None:
        store = _mock_store()
        with (
            patch.object(recorder, "get_current_session_id", return_value=_SESSION),
            patch.object(recorder, "get_evidence_store", return_value=store),
        ):
            await recorder.record_fill_evidence(
                **_fill_kwargs(
                    side="SELL",
                    realized_pnl=Decimal("42.5"),
                    cost_basis=Decimal("500"),
                    lot_id="lot-9",
                )
            )

        acct = store.insert_accounting_record.await_args.args[0]
        assert acct.realized_pnl == Decimal("42.5")
        assert acct.cost_basis == Decimal("500")
        assert acct.lot_id == "lot-9"
        assert acct.idempotency_key == "acct:ord-1"

    @pytest.mark.asyncio
    async def test_noop_when_no_active_session(self) -> None:
        store = _mock_store()
        with (
            patch.object(recorder, "get_current_session_id", return_value=None),
            patch.object(recorder, "get_evidence_store", return_value=store),
        ):
            await recorder.record_fill_evidence(**_fill_kwargs())

        store.insert_tca_record.assert_not_awaited()
        store.insert_accounting_record.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_noop_when_store_not_initialised(self) -> None:
        with (
            patch.object(recorder, "get_current_session_id", return_value=_SESSION),
            patch.object(
                recorder,
                "get_evidence_store",
                side_effect=RuntimeError("not initialised"),
            ),
        ):
            # Must not raise
            await recorder.record_fill_evidence(**_fill_kwargs())

    @pytest.mark.asyncio
    async def test_swallows_insert_failure(self) -> None:
        store = _mock_store()
        store.insert_tca_record = AsyncMock(side_effect=RuntimeError("db down"))
        with (
            patch.object(recorder, "get_current_session_id", return_value=_SESSION),
            patch.object(recorder, "get_evidence_store", return_value=store),
        ):
            # Must not raise — trading continues even if evidence write fails
            await recorder.record_fill_evidence(**_fill_kwargs())


# ---------------------------------------------------------------------------
# record_signal_evidence
# ---------------------------------------------------------------------------


class TestRecordSignalEvidence:
    @pytest.mark.asyncio
    async def test_writes_one_snapshot_per_result(self) -> None:
        store = _mock_store()
        results = [
            StrategyResult(
                strategy_id="sma_crossover", symbol="BTC/USDT", signal="BUY", strength=0.8
            ),
            StrategyResult(
                strategy_id="rsi_mean_reversion", symbol="ETH/USDT", signal="HOLD", strength=0.1
            ),
        ]
        with (
            patch.object(recorder, "get_current_session_id", return_value=_SESSION),
            patch.object(recorder, "get_evidence_store", return_value=store),
        ):
            await recorder.record_signal_evidence(results)

        assert store.insert_signal_snapshot.await_count == 2
        snap = store.insert_signal_snapshot.await_args_list[0].args[0]
        assert snap.session_id == _SESSION
        assert snap.strength == Decimal("0.8")

    @pytest.mark.asyncio
    async def test_noop_when_no_session(self) -> None:
        store = _mock_store()
        with (
            patch.object(recorder, "get_current_session_id", return_value=None),
            patch.object(recorder, "get_evidence_store", return_value=store),
        ):
            await recorder.record_signal_evidence(
                [StrategyResult(strategy_id="sma_crossover", signal="BUY", strength=0.5)]
            )
        store.insert_signal_snapshot.assert_not_awaited()


# ---------------------------------------------------------------------------
# AccountingLedger.realized_for_sell
# ---------------------------------------------------------------------------


class TestRealizedForSell:
    def test_returns_pnl_and_cost_for_matched_sell(self) -> None:
        ledger = AccountingLedger()
        ledger.record_trade("BTC/USDT", "BUY", quantity="0.1", price="50000", order_id="b1")
        sell_lot = ledger.record_trade(
            "BTC/USDT", "SELL", quantity="0.1", price="55000", order_id="s1"
        )
        result = ledger.realized_for_sell(sell_lot.lot_id)
        assert result is not None
        pnl, cost = result
        assert cost == Decimal("5000.00000000")
        assert pnl == Decimal("500.00000000")

    def test_returns_none_for_buy_lot(self) -> None:
        ledger = AccountingLedger()
        buy_lot = ledger.record_trade("BTC/USDT", "BUY", quantity="0.1", price="50000")
        assert ledger.realized_for_sell(buy_lot.lot_id) is None


# ---------------------------------------------------------------------------
# EvidenceStore.count_round_trips
# ---------------------------------------------------------------------------


class TestCountRoundTrips:
    @pytest.mark.asyncio
    async def test_counts_realized_sells(self) -> None:
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(return_value=7)
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        store = EvidenceStore(mock_pool)
        count = await store.count_round_trips(_SESSION)

        assert count == 7
        sql = mock_conn.fetchval.await_args.args[0]
        assert "realized_pnl IS NOT NULL" in sql
