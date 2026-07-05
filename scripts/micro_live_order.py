"""Operator trigger: place ONE gated micro-live order by hand.

This is the manual operator interface to MicroLiveExecutor. It is intentionally
a deliberate command-line action, never an automated job. Every safety gate
applies; by default (live_trading_enabled=false + the gate's global constant)
it REFUSES and prints why — which is the correct, safe behaviour.

On testnet (BINANCE_TESTNET=true, the default) any order that does get through
uses fake money.

Usage:
  python scripts/micro_live_order.py --side BUY --usd 6 --symbol BTC/USDT \
      --operator alice [--yes]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from trading_bot.config import get_settings  # noqa: E402
from trading_bot.exchange.binance import BinanceExchange  # noqa: E402
from trading_bot.execution.micro_live_executor import (  # noqa: E402
    MicroLiveExecutor,
    MicroLiveRefusedError,
)
from trading_bot.promotion.micro_live import MicroLiveConfig, MicroLiveGate  # noqa: E402


def _build(
    operator: str, symbol: str, strategy_id: str
) -> tuple[BinanceExchange, MicroLiveExecutor]:
    settings = get_settings()
    exchange = BinanceExchange(
        api_key=settings.binance.api_key,
        api_secret=settings.binance.api_secret,
        testnet=settings.binance.testnet,
    )
    # Lock the session to exactly this symbol + strategy.
    gate = MicroLiveGate(
        MicroLiveConfig(
            allowed_symbols=frozenset({symbol}),
            allowed_strategies=frozenset({strategy_id}),
        )
    )
    # Explicit operator enablement (still blocked by the hard code/flag gates).
    gate.enable(strategy_id=strategy_id, symbol=symbol, operator=operator)
    executor = MicroLiveExecutor(exchange, gate, strategy_id=strategy_id)
    return exchange, executor


async def _run(args: argparse.Namespace) -> int:
    exchange, executor = _build(args.operator, args.symbol, args.strategy)
    try:
        fill = await executor.submit(
            symbol=args.symbol,
            side=args.side,
            usd_notional=args.usd,
            operator=args.operator,
        )
        print(f"✅ order filled: {fill}")
        return 0
    except MicroLiveRefusedError as exc:
        print(f"⛔ refused (safe): {exc}")
        return 2
    finally:
        await exchange.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="micro-live-order", description=__doc__)
    parser.add_argument("--side", required=True, choices=["BUY", "SELL"])
    parser.add_argument("--usd", required=True, type=float, help="Order notional in USD (≤ $50).")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--operator", required=True, help="Operator name for the audit trail.")
    parser.add_argument("--strategy", default="operator")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    settings = get_settings()
    print(
        f"micro-live order: {args.side} ~${args.usd} {args.symbol}  "
        f"(testnet={settings.binance.testnet}, operator={args.operator})"
    )
    if not args.yes:
        reply = input(
            "This attempts a REAL order on the configured endpoint. Type 'yes' to proceed: "
        )
        if reply.strip().lower() != "yes":
            print("aborted.")
            sys.exit(1)

    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
