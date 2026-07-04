"""Unit tests for the paper_orders → evidence backfill.

Covers:
- backfill reconstructs one TCA + one accounting record per filled order
- deterministic idempotency keys match the live recorder (tca:/acct:)
- realized PnL / cost-basis reconstructed for SELL round-trips via FIFO replay
- needs_backfill compares filled orders vs recorded TCA rows
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_bot.evidence.backfill import (
    backfill_evidence_from_paper_orders,
    needs_backfill,
)

_SESSION = uuid.uuid4()


def _row(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {
        "order_id": "o1",
        "strategy_id": "rsi_mean_reversion",
        "symbol": "BTC/USDT",
        "side": "buy",
        "filled_qty": Decimal("0.1"),
        "fill_price": Decimal("50000"),
        "status": "filled",
        "created_at": datetime.now(UTC),
    }
    base.update(kw)
    return base


def _store_with_fetch(rows: list[dict[str, object]]) -> tuple[MagicMock, MagicMock]:
    mock_pool = MagicMock()
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=rows)
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    store = MagicMock()
    store.insert_tca_record = AsyncMock(return_value=True)
    store.insert_accounting_record = AsyncMock(return_value=True)
    return store, mock_pool


class TestBackfill:
    @pytest.mark.asyncio
    async def test_reconstructs_records_with_matching_idem_keys(self) -> None:
        rows = [_row(order_id="o1", side="buy")]
        store, pool = _store_with_fetch(rows)

        inserted = await backfill_evidence_from_paper_orders(pool, store, _SESSION)

        assert inserted == 1
        store.insert_tca_record.assert_awaited_once()
        store.insert_accounting_record.assert_awaited_once()
        tca = store.insert_tca_record.await_args.args[0]
        acct = store.insert_accounting_record.await_args.args[0]
        assert tca.idempotency_key == "tca:o1"
        assert acct.idempotency_key == "acct:o1"
        assert tca.session_id == _SESSION
        assert tca.signal_price == tca.fill_price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_reconstructs_realized_pnl_for_sell_round_trip(self) -> None:
        t0 = datetime.now(UTC)
        rows = [
            _row(order_id="b1", side="buy", fill_price=Decimal("50000"), created_at=t0),
            _row(
                order_id="s1",
                side="sell",
                fill_price=Decimal("55000"),
                created_at=t0 + timedelta(hours=1),
            ),
        ]
        store, pool = _store_with_fetch(rows)

        inserted = await backfill_evidence_from_paper_orders(pool, store, _SESSION)

        assert inserted == 2
        # The second accounting record (the SELL) carries realized PnL
        sell_acct = store.insert_accounting_record.await_args_list[1].args[0]
        assert sell_acct.side == "sell"
        assert sell_acct.cost_basis == Decimal("5000.00000000")
        # 0.1 * 55000 - 0.1 * 50000 - fees(0.1*50000*0.001 + 0.1*55000*0.001)
        assert sell_acct.realized_pnl is not None
        assert sell_acct.realized_pnl > Decimal("489")
        assert sell_acct.realized_pnl < Decimal("500")

    @pytest.mark.asyncio
    async def test_buy_has_no_realized_pnl(self) -> None:
        store, pool = _store_with_fetch([_row(order_id="o1", side="buy")])
        await backfill_evidence_from_paper_orders(pool, store, _SESSION)
        acct = store.insert_accounting_record.await_args.args[0]
        assert acct.realized_pnl is None
        assert acct.cost_basis is None


class TestNeedsBackfill:
    @pytest.mark.asyncio
    async def test_true_when_filled_exceeds_recorded(self) -> None:
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(side_effect=[78, 0])  # filled, recorded
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        assert await needs_backfill(mock_pool, _SESSION) is True

    @pytest.mark.asyncio
    async def test_false_when_all_recorded(self) -> None:
        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.fetchval = AsyncMock(side_effect=[78, 78])
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        assert await needs_backfill(mock_pool, _SESSION) is False
