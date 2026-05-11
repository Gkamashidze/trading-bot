"""Portfolio state rebuilder — authoritative crash recovery.

Strategy:
  1. Load latest on-disk snapshot (hourly, written to /data/snapshots/).
  2. Apply it to PortfolioManager (sets cash, positions, avg_cost).
  3. Replay any FILLED paper_orders rows whose created_at > snapshot.captured_at.
     This bridges the gap between the last snapshot and the crash moment.

If no snapshot exists, replay ALL fills from paper_orders from scratch.

Typical RPO after this runs: 0 seconds (fills are persisted synchronously
relative to apply_fill; the only true gap is the fire-and-forget async write
in tracker._persist — but ON CONFLICT DO NOTHING makes that idempotent once
the row lands).

Called once in main._startup() after the DB pool is ready.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trading_bot.core.models import ExchangeId, OrderRequest, OrderSide, OrderType
from trading_bot.disaster_recovery.snapshotter import (
    StateSnapshot,
    restore_latest_snapshot,
)
from trading_bot.observability.logging import get_logger
from trading_bot.portfolio.manager import get_portfolio_manager

log = get_logger(__name__)

_TAKER_FEE = Decimal("0.001")
_EPOCH = "1970-01-01T00:00:00+00:00"


async def rebuild_portfolio(pool: Any) -> tuple[StateSnapshot | None, int]:
    """Restore portfolio from snapshot + replay newer DB fills.

    Returns (snapshot_used, fills_replayed).
    snapshot_used is None when no snapshot existed (cold start).
    """
    portfolio = get_portfolio_manager()
    snap = restore_latest_snapshot()

    if snap is not None:
        portfolio.restore_from_snapshot(snap)
        since_iso = snap.captured_at
    else:
        log.info("portfolio_rebuild_no_snapshot", note="replaying all fills from DB")
        since_iso = _EPOCH

    since_dt = datetime.fromisoformat(since_iso)
    fills_replayed = await _replay_fills_after(pool, portfolio, since_dt)

    log.info(
        "portfolio_rebuild_complete",
        snapshot_captured_at=snap.captured_at if snap else None,
        fills_replayed=fills_replayed,
        cash=str(portfolio.get_snapshot().cash_balance),
        open_positions=len(portfolio._qty),
    )
    return snap, fills_replayed


async def _replay_fills_after(
    pool: Any,
    portfolio: Any,
    since: datetime,
) -> int:
    """Fetch FILLED rows from paper_orders after `since` and replay them."""
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT symbol, side, strategy_id,
                       filled_qty, fill_price, created_at
                FROM   paper_orders
                WHERE  status      = 'filled'
                  AND  filled_qty  IS NOT NULL
                  AND  fill_price  IS NOT NULL
                  AND  created_at  > $1
                ORDER  BY created_at ASC
                """,
                since,
            )
    except Exception as exc:
        log.error("portfolio_rebuild_db_fetch_failed", error=str(exc))
        return 0

    replayed = 0
    for row in rows:
        try:
            side = OrderSide.BUY if str(row["side"]).lower() == "buy" else OrderSide.SELL
            order = OrderRequest(
                symbol=row["symbol"],
                exchange=ExchangeId.BINANCE,
                side=side,
                order_type=OrderType.MARKET,
                quantity=Decimal(str(row["filled_qty"])),
                strategy_id=str(row["strategy_id"] or ""),
            )
            fill_price = Decimal(str(row["fill_price"]))
            portfolio.apply_fill(order, fill_price, fee_rate=_TAKER_FEE)

            # Preserve original opened_at if the position was just opened
            sym = row["symbol"]
            if sym in portfolio._opened_at and row["created_at"] is not None:
                created = row["created_at"]
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                if not created.tzinfo:
                    created = created.replace(tzinfo=UTC)
                if side == OrderSide.BUY and portfolio._qty.get(sym, Decimal(0)) > 0:
                    portfolio._opened_at[sym] = created

            replayed += 1
        except Exception as exc:
            log.warning(
                "portfolio_rebuild_row_failed",
                symbol=row["symbol"],
                side=row["side"],
                error=str(exc),
            )

    return replayed
