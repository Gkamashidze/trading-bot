"""Global pytest fixtures and configuration.

Available fixtures:
- sample_ohlcv_df: a small validated OHLCV DataFrame
- mock_exchange: an AsyncMock of ExchangeInterface
- mock_audit_log: an AsyncMock of AuditLogInterface
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from trading_bot.core.models import ExchangeId, OHLCVBar


@pytest.fixture
def sample_ohlcv_bars() -> list[OHLCVBar]:
    """100 synthetic BTC/USDT daily bars for testing."""
    bars = []
    base_price = Decimal("50000")
    base_time = datetime(2024, 1, 1, tzinfo=UTC)

    for i in range(100):
        open_price = base_price + Decimal(str(i * 100))
        high_price = open_price + Decimal("500")
        low_price = open_price - Decimal("300")
        close_price = open_price + Decimal("200")

        bars.append(
            OHLCVBar(
                symbol="BTC/USDT",
                exchange=ExchangeId.BINANCE,
                timeframe="1d",
                open_time=base_time + timedelta(days=i),
                close_time=base_time + timedelta(days=i, hours=23, minutes=59, seconds=59),
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=Decimal("1000"),
                quote_volume=Decimal("50000000"),
                trade_count=50000,
                source="test_fixture",
            )
        )
    return bars


@pytest.fixture
def sample_ohlcv_df(sample_ohlcv_bars: list[OHLCVBar]) -> pd.DataFrame:
    """Convert sample bars to a validated DataFrame."""
    rows = []
    for bar in sample_ohlcv_bars:
        rows.append(
            {
                "open_time": bar.open_time,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
                "symbol": bar.symbol,
                "exchange": str(bar.exchange),
                "timeframe": bar.timeframe,
            }
        )
    return pd.DataFrame(rows)


@pytest.fixture
def mock_exchange() -> AsyncMock:
    """Mock ExchangeInterface for unit tests."""
    from trading_bot.core.contracts import ExchangeInterface

    mock = AsyncMock(spec=ExchangeInterface)
    mock.health_check.return_value = True
    mock.get_server_time.return_value = datetime.now(UTC)
    return mock


@pytest.fixture
def mock_audit_log() -> AsyncMock:
    """Mock AuditLogInterface for unit tests."""
    from trading_bot.core.contracts import AuditLogInterface

    mock = AsyncMock(spec=AuditLogInterface)
    mock.append.return_value = "abc123def456"
    mock.get_chain_head.return_value = None
    mock.verify_chain.return_value = True
    return mock
