"""Download BTC/USDT 1h history from Binance (public, no auth) for backtesting.

Writes to data/raw/binance/BTC_USDT/1h/ in the schema the engine expects
(open_time, open, high, low, close, volume). Idempotent-ish: overwrites the
single output file. Uses the PRODUCTION endpoint (the app's default adapter is
testnet, which has no historical klines).

Run:  python scripts/download_backtest_data.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import ccxt.async_support as ccxt
import pandas as pd

_SYMBOL = "BTC/USDT"
_TF = "1h"
_INTERVAL_MS = 3_600_000
_START = "2022-01-01T00:00:00Z"
_END = "2026-07-01T00:00:00Z"
_ROOT = Path(__file__).resolve().parent.parent
_OUTDIR = _ROOT / "data/raw/binance/BTC_USDT/1h"


async def _download() -> pd.DataFrame:
    ex = ccxt.binance({"enableRateLimit": True})
    since = ex.parse8601(_START)
    end = ex.parse8601(_END)
    rows: list[list[float]] = []
    try:
        while since < end:
            batch = await ex.fetch_ohlcv(_SYMBOL, timeframe=_TF, since=since, limit=1000)
            if not batch:
                break
            rows.extend(batch)
            since = batch[-1][0] + _INTERVAL_MS
            if len(batch) < 1000 and batch[-1][0] >= end - _INTERVAL_MS:
                break
    finally:
        await ex.close()

    df = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ms")
    df = df[df["ms"] < end]
    df["open_time"] = pd.to_datetime(df["ms"], unit="ms", utc=True)
    return df[["open_time", "open", "high", "low", "close", "volume"]].sort_values("open_time")


def main() -> None:
    df = asyncio.run(_download())
    _OUTDIR.mkdir(parents=True, exist_ok=True)
    out = _OUTDIR / "btc_usdt_1h_2022_2026.parquet"
    df.to_parquet(out, index=False)
    print(f"Wrote {len(df)} bars {df['open_time'].min()} -> {df['open_time'].max()} to {out}")


if __name__ == "__main__":
    main()
