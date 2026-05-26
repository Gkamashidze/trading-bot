"""ETF trading CLI — entry point for trading-bot-etf script.

Usage
-----
  trading-bot-etf test-synthetic   --symbols SPY,QQQ,SOXX,IBIT --min-cycles 5
  trading-bot-etf backtest         --symbols SPY --start 2024-01-01 --end 2025-01-01
  trading-bot-etf paper-execution-test --symbols SPY --qty 1

Or invoke as a module:
  python -m trading_bot.cli <command> [options]
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Synchronous entry point for the trading-bot-etf script."""
    from trading_bot.cli.etf_commands import run_backtest, run_paper_execution, run_test_synthetic

    parser = argparse.ArgumentParser(
        prog="trading-bot-etf",
        description="Alpaca ETF trading commands — paper mode by default.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── test-synthetic ────────────────────────────────────────────────────
    p_synth = sub.add_parser(
        "test-synthetic",
        help="Run in-memory synthetic forced-trade tests (no API calls).",
    )
    p_synth.add_argument(
        "--symbols",
        default="SPY,QQQ,SOXX,IBIT",
        help="Comma-separated ETF symbols to test.",
    )
    p_synth.add_argument(
        "--min-cycles",
        type=int,
        default=5,
        help="Minimum buy/sell cycles required per symbol (default: 5).",
    )
    p_synth.add_argument(
        "--strategy",
        choices=["sma", "rsi", "both"],
        default="both",
        help="Strategy to test (default: both).",
    )

    # ── backtest ───────────────────────────────────────────────────────────
    p_bt = sub.add_parser(
        "backtest",
        help="Run historical backtest for ETF symbols using yfinance data.",
    )
    p_bt.add_argument("--symbols", default="SPY,QQQ,SOXX,IBIT")
    p_bt.add_argument("--start", default="2024-01-01", help="Start date YYYY-MM-DD.")
    p_bt.add_argument("--end", default="2025-01-01", help="End date YYYY-MM-DD.")
    p_bt.add_argument("--strategy", choices=["sma", "rsi", "both"], default="both")
    p_bt.add_argument("--capital", type=float, default=100_000.0, help="Initial capital USD.")

    # ── paper-execution-test ───────────────────────────────────────────────
    p_paper = sub.add_parser(
        "paper-execution-test",
        help="Submit a test order to Alpaca paper API. Requires ALPACA_API_KEY + ALPACA_SECRET_KEY.",  # noqa: E501
    )
    p_paper.add_argument("--symbols", default="SPY")
    p_paper.add_argument("--qty", type=float, default=1.0, help="Shares per test order.")

    args = parser.parse_args()

    if args.command == "test-synthetic":
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        ok = run_test_synthetic(symbols=symbols, min_cycles=args.min_cycles, strategy=args.strategy)
        sys.exit(0 if ok else 1)

    elif args.command == "backtest":
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        run_backtest(
            symbols=symbols,
            start=args.start,
            end=args.end,
            strategy=args.strategy,
            capital=args.capital,
        )

    elif args.command == "paper-execution-test":
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        import asyncio

        asyncio.run(run_paper_execution(symbols=symbols, qty=args.qty))
