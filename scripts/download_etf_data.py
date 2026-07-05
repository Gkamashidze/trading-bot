"""Download ETF daily OHLCV via yfinance for the walk-forward edge test.

Fetches SPY / QQQ / SOXX (Wave-1 ETFs, asset_universe.yaml phase 5) as
split/dividend-adjusted daily bars and writes them to Parquet in the same
schema as the crypto data (open_time, open, high, low, close, volume).

Adjusted prices (auto_adjust=True) are used so buy-and-hold reflects real
total return (dividends reinvested) — the honest benchmark for equities.

Data is gitignored (regenerated on demand), like the BTC parquet.

Run:  uv run python scripts/download_etf_data.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

_ROOT = Path(__file__).resolve().parent.parent
_OUTDIR = _ROOT / "data/raw/etf"
_SYMBOLS = ("SPY", "QQQ", "SOXX")


def _download_one(symbol: str) -> pd.DataFrame:
    raw = yf.Ticker(symbol).history(period="max", interval="1d", auto_adjust=True)
    if raw.empty:
        raise SystemExit(f"yfinance returned no data for {symbol}")
    df = raw.reset_index()
    # yfinance column is "Date" (tz-aware or naive) → normalise to UTC open_time.
    df["open_time"] = pd.to_datetime(df["Date"], utc=True)
    out = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    cols = ["open_time", "open", "high", "low", "close", "volume"]
    return out[cols].sort_values("open_time").reset_index(drop=True)


def main() -> None:
    _OUTDIR.mkdir(parents=True, exist_ok=True)
    for symbol in _SYMBOLS:
        df = _download_one(symbol)
        out = _OUTDIR / f"{symbol.lower()}_1d.parquet"
        df.to_parquet(out, index=False)
        print(
            f"{symbol}: {len(df):,} daily bars "
            f"{df['open_time'].min().date()} → {df['open_time'].max().date()} → {out.name}"
        )


if __name__ == "__main__":
    sys.exit(main())
