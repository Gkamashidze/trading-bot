"""NYSE market hours and trading calendar utilities.

Uses pandas-market-calendars (already a project dependency).
The authoritative open/close check for live use is AlpacaExchange._is_market_open(),
which calls the Alpaca /clock endpoint. This module provides an offline fallback
and is used directly in CLI commands and synthetic tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

_EASTERN = ZoneInfo("America/New_York")


def _nyse() -> mcal.MarketCalendar:
    """Lazy-load NYSE calendar so import overhead stays at call time."""
    return mcal.get_calendar("NYSE")


def is_equity_market_open(now: datetime | None = None) -> bool:
    """Return True if NYSE is currently in a regular trading session.

    Checks pandas-market-calendars for holiday awareness.
    Fast-path: rejects weekends before hitting the calendar.

    Args:
        now: UTC- or ET-aware datetime. Defaults to current local time in ET.

    Raises:
        ValueError: if a naive (tz-unaware) datetime is passed.
    """
    if now is None:
        now_et = datetime.now(_EASTERN)
    else:
        if now.tzinfo is None:
            raise ValueError("datetime must be timezone-aware; got naive datetime")
        now_et = now.astimezone(_EASTERN)

    if now_et.weekday() >= 5:  # Saturday=5, Sunday=6
        return False

    today_str = now_et.date().isoformat()
    schedule = _nyse().schedule(start_date=today_str, end_date=today_str)
    if schedule.empty:
        return False  # holiday

    market_open_utc: datetime = schedule.iloc[0]["market_open"].to_pydatetime()
    market_close_utc: datetime = schedule.iloc[0]["market_close"].to_pydatetime()

    now_utc = now_et.astimezone(UTC)
    return market_open_utc <= now_utc < market_close_utc


def next_market_open(now: datetime | None = None) -> datetime:
    """Return the next NYSE session open as a UTC-aware datetime.

    Args:
        now: UTC- or ET-aware datetime. Defaults to current local time in ET.

    Raises:
        ValueError: if a naive datetime is passed.
        RuntimeError: if no open is found within the next 10 calendar days.
    """
    if now is None:
        now = datetime.now(_EASTERN)
    if now.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")

    start = now.astimezone(_EASTERN).date()
    end = start + timedelta(days=10)
    schedule = _nyse().schedule(
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )

    for _, row in schedule.iterrows():
        open_utc: datetime = row["market_open"].to_pydatetime()
        if open_utc > now.astimezone(UTC):
            return open_utc

    raise RuntimeError("Could not find next NYSE open within 10 days")


def trading_days_between(start: datetime, end: datetime) -> int:
    """Return the number of NYSE trading days between two UTC-aware datetimes."""
    schedule = _nyse().schedule(
        start_date=start.astimezone(_EASTERN).date().isoformat(),
        end_date=end.astimezone(_EASTERN).date().isoformat(),
    )
    return len(schedule)
