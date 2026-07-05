"""Download BTC daily OHLCV + non-price signals (Fear&Greed, funding rate).

Builds one daily dataset for the "does sentiment have edge?" test:
  open_time, open, high, low, close, volume, fear_greed, funding_rate

Sources (all public, no auth):
  • BTC/USDT daily bars      — Binance production (ccxt)
  • Fear & Greed index       — alternative.me (daily, 2018-02+)
  • Funding rate             — Binance USDT-M futures (8h, 2019-09+; daily mean)

Signals are left-joined onto the price bars; rows before a signal exists carry
NaN (the strategy handles that). Data is gitignored (regenerated on demand).

Run:  uv run python scripts/download_signal_data.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import ccxt.async_support as ccxt
import httpx
import pandas as pd

_START = "2018-01-01T00:00:00Z"
_END = "2026-07-01T00:00:00Z"
_DAY_MS = 86_400_000
_ROOT = Path(__file__).resolve().parent.parent
_OUTDIR = _ROOT / "data/raw/signals"
_FNG_URL = "https://api.alternative.me/fng/?limit=0&format=json"
_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"

# (ccxt spot symbol, futures funding symbol, output file stem)
_ASSETS = [
    ("BTC/USDT", "BTCUSDT", "btc"),
    ("ETH/USDT", "ETHUSDT", "eth"),
]


async def _download_daily(symbol: str) -> pd.DataFrame:
    ex = ccxt.binance({"enableRateLimit": True})
    since = ex.parse8601(_START)
    end = ex.parse8601(_END)
    rows: list[list[float]] = []
    try:
        while since < end:
            batch = await ex.fetch_ohlcv(symbol, timeframe="1d", since=since, limit=1000)
            if not batch:
                break
            rows.extend(batch)
            since = batch[-1][0] + _DAY_MS
            if len(batch) < 1000:
                break
    finally:
        await ex.close()
    df = pd.DataFrame(rows, columns=["ms", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ms")
    df = df[df["ms"] < end]
    df["date"] = pd.to_datetime(df["ms"], unit="ms", utc=True).dt.normalize()
    return df[["date", "open", "high", "low", "close", "volume"]].sort_values("date")


def _download_fear_greed() -> pd.DataFrame:
    data = httpx.get(_FNG_URL, timeout=30).json()["data"]
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True).dt.normalize()
    df["fear_greed"] = df["value"].astype(int)
    return df[["date", "fear_greed"]].sort_values("date")


def _download_funding(funding_symbol: str) -> pd.DataFrame:
    start_ms = int(pd.Timestamp(_START).timestamp() * 1000)
    end_ms = int(pd.Timestamp(_END).timestamp() * 1000)
    rows: list[dict] = []  # type: ignore[type-arg]
    since = start_ms
    with httpx.Client(timeout=30) as client:
        while since < end_ms:
            resp = client.get(
                _FUNDING_URL,
                params={"symbol": funding_symbol, "startTime": since, "limit": 1000},
            )
            batch = resp.json()
            if not batch:
                break
            rows.extend(batch)
            since = int(batch[-1]["fundingTime"]) + 1
            if len(batch) < 1000:
                break
    if not rows:
        return pd.DataFrame(columns=["date", "funding_rate"])
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["fundingTime"].astype(int), unit="ms", utc=True).dt.normalize()
    df["funding_rate"] = df["fundingRate"].astype(float)
    # 8h → daily mean funding rate.
    return df.groupby("date", as_index=False)["funding_rate"].mean()


def main() -> None:
    _OUTDIR.mkdir(parents=True, exist_ok=True)
    fng = _download_fear_greed()  # crypto-wide, shared across assets

    for spot_symbol, funding_symbol, stem in _ASSETS:
        daily = asyncio.run(_download_daily(spot_symbol))
        funding = _download_funding(funding_symbol)
        merged = daily.merge(fng, on="date", how="left").merge(funding, on="date", how="left")
        merged = merged.rename(columns={"date": "open_time"}).sort_values("open_time")

        out = _OUTDIR / f"{stem}_daily_signals.parquet"
        merged.to_parquet(out, index=False)
        fng_cov = merged["fear_greed"].notna().sum()
        fund_cov = merged["funding_rate"].notna().sum()
        print(
            f"{spot_symbol}: {len(merged)} daily bars {merged['open_time'].min().date()} → "
            f"{merged['open_time'].max().date()} → {out.name} "
            f"(F&G {fng_cov}, funding {fund_cov})"
        )


if __name__ == "__main__":
    main()
