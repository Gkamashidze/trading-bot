"""Validate the live order pipeline against Binance TESTNET (fake money, zero risk).

Safe by construction: refuses to run unless testnet mode is active, so it can
NEVER place a real-money order. Exercises the full path implemented in
BinanceExchange: load constraints → reference price → place_order → poll status
→ flatten. Read-only checks always run; the order round-trip runs only when
testnet API credentials are configured.

Setup (one-time):
  1. Create a testnet account + API key at https://testnet.binance.vision
  2. export BINANCE_API_KEY=...  BINANCE_API_SECRET=...  BINANCE_TESTNET=true
  3. python scripts/validate_testnet_order.py
"""

from __future__ import annotations

import asyncio
import sys
from decimal import Decimal
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from trading_bot.config import get_settings  # noqa: E402
from trading_bot.core.models import ExchangeId, OrderRequest, OrderSide, OrderType  # noqa: E402
from trading_bot.exchange.binance import BinanceExchange, _constraints_from_market  # noqa: E402

_SYMBOL = "BTC/USDT"


async def _run() -> None:
    settings = get_settings()
    if not settings.binance.testnet:
        raise SystemExit("REFUSING: BINANCE_TESTNET is not true. This script is testnet-only.")

    ex = BinanceExchange(
        api_key=settings.binance.api_key,
        api_secret=settings.binance.api_secret,
        testnet=True,
    )
    try:
        # ── Read-only: always runs (no auth needed) ───────────────────────────
        markets = await ex._client.load_markets()
        constraints = _constraints_from_market(markets.get(_SYMBOL, {}))
        price = await ex.reference_price(_SYMBOL)
        print(f"[read-only] {_SYMBOL} testnet price = {price}")
        print(
            f"[read-only] constraints: step={constraints.qty_step} "
            f"min_qty={constraints.min_qty} min_notional={constraints.min_notional}"
            if constraints
            else "[read-only] constraints unavailable"
        )

        if not (settings.binance.api_key and settings.binance.api_secret):
            print(
                "\nNo testnet API credentials set — read-only checks passed.\n"
                "To validate real order placement, set BINANCE_API_KEY / "
                "BINANCE_API_SECRET to testnet keys and re-run."
            )
            return

        if constraints is None or price is None:
            raise SystemExit("cannot size order: constraints/price unavailable")

        # ── Order round-trip: tiny order ~1.5x min notional ───────────────────
        target_notional = constraints.min_notional * Decimal("1.5")
        qty = (target_notional / price).quantize(constraints.qty_step)
        print(f"\n[order] BUY {qty} {_SYMBOL} (~${target_notional} notional) on TESTNET…")

        buy = await ex.place_order(
            OrderRequest(
                symbol=_SYMBOL,
                exchange=ExchangeId.BINANCE,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=qty,
            )
        )
        print(f"[order] BUY fill: {buy}")

        status = await ex.get_order_status(buy["exchange_order_id"], _SYMBOL)
        print(f"[order] status poll: {status.get('status')}")

        sell = await ex.place_order(
            OrderRequest(
                symbol=_SYMBOL,
                exchange=ExchangeId.BINANCE,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                quantity=Decimal(buy["filled_quantity"]),
            )
        )
        print(f"[order] SELL fill (flatten): {sell}")
        print("\n✅ Testnet order pipeline validated end-to-end (fake money).")
    finally:
        await ex.close()


if __name__ == "__main__":
    asyncio.run(_run())
