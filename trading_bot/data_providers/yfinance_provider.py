"""yfinance data provider for equity/ETF historical data (SPY, QQQ, SOXX).

yfinance is used as a secondary/validation source, not primary. It does
not guarantee point-in-time correctness (data may be restated). Use only
for exploratory research in notebooks, not for production backtests.

If Yahoo blocks access, migrate to Polygon.io or Tiingo (see vendor risk ADR).
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from trading_bot.core.contracts import DataProviderInterface
from trading_bot.core.exceptions import DataFetchError
from trading_bot.observability.logging import get_logger
from trading_bot.observability.tracing import start_span

log = get_logger(__name__)


class YFinanceProvider(DataProviderInterface):
    """yfinance-based data provider for equities and ETFs."""

    async def get_market_data(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV data via yfinance.

        Timeframe mapping: "1d" → "1d", "1h" → "1h", "1wk" → "1wk".
        Returns UTC-aware datetimes.
        """
        import yfinance as yf  # lazy import — not installed in all envs

        with start_span(
            "data_provider.yfinance.fetch",
            {"symbol": symbol, "timeframe": timeframe},
        ):
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(
                    start=start.date().isoformat(),
                    end=end.date().isoformat(),
                    interval=_map_timeframe(timeframe),
                    auto_adjust=True,     # applies splits/dividends
                    prepost=False,        # regular session only
                )

                if df.empty:
                    log.warning(
                        "yfinance_empty_response",
                        symbol=symbol,
                        start=start.isoformat(),
                        end=end.isoformat(),
                    )
                    return []

                results = []
                for ts, row in df.iterrows():
                    open_time = ts.to_pydatetime().replace(tzinfo=timezone.utc)
                    results.append(
                        {
                            "open_time": open_time,
                            "close_time": open_time,  # yfinance gives open time only
                            "open": Decimal(str(row["Open"])),
                            "high": Decimal(str(row["High"])),
                            "low": Decimal(str(row["Low"])),
                            "close": Decimal(str(row["Close"])),
                            "volume": Decimal(str(row["Volume"])),
                            "quote_volume": Decimal("0"),
                            "source": "yfinance",
                        }
                    )
                return results

            except Exception as e:
                raise DataFetchError(f"yfinance fetch failed for {symbol}: {e}") from e

    async def get_corporate_actions(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Return dividend and split history for a symbol."""
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        actions = ticker.actions
        if actions is None or actions.empty:
            return []
        mask = (actions.index >= start.date().isoformat()) & (
            actions.index <= end.date().isoformat()
        )
        filtered = actions[mask]
        results = []
        for ts, row in filtered.iterrows():
            results.append(
                {
                    "date": ts.to_pydatetime().replace(tzinfo=timezone.utc),
                    "dividend": Decimal(str(row.get("Dividends", 0))),
                    "split_ratio": Decimal(str(row.get("Stock Splits", 1))),
                }
            )
        return results

    async def get_market_calendar(self, exchange: str, year: int) -> list[dict[str, Any]]:
        """Return trading calendar from pandas_market_calendars."""
        import pandas_market_calendars as mcal

        cal = mcal.get_calendar(exchange)
        schedule = cal.schedule(
            start_date=f"{year}-01-01",
            end_date=f"{year}-12-31",
        )
        return [
            {
                "date": row.name.date().isoformat(),
                "market_open": row["market_open"].isoformat(),
                "market_close": row["market_close"].isoformat(),
            }
            for _, row in schedule.iterrows()
        ]

    async def health_check(self) -> bool:
        """Check if yfinance can reach Yahoo Finance."""
        try:
            import yfinance as yf

            ticker = yf.Ticker("SPY")
            info = ticker.fast_info
            return bool(info)
        except Exception as e:
            log.warning("yfinance_health_failed", error=str(e))
            return False


def _map_timeframe(tf: str) -> str:
    """Map internal timeframe strings to yfinance interval format."""
    _map = {
        "1m": "1m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
        "1w": "1wk",
        "1M": "1mo",
    }
    return _map.get(tf, "1d")
