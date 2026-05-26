"""Unit tests for strategies/runner.py — signal refresh pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd

from trading_bot.core.exceptions import DataStalenessError


def _make_bars(stale: bool = False) -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame with open_time set to recent or stale."""
    if stale:
        last_time = pd.Timestamp(datetime.now(UTC) - timedelta(days=3))
    else:
        last_time = pd.Timestamp(datetime.now(UTC) - timedelta(hours=1))

    rows = [
        {
            "open_time": last_time - timedelta(days=i),
            "open": 50000.0,
            "high": 51000.0,
            "low": 49000.0,
            "close": 50500.0,
            "volume": 100.0,
        }
        for i in range(5, -1, -1)
    ]
    rows[-1]["open_time"] = last_time
    return pd.DataFrame(rows)


def _mock_settings(symbols: list[str] | None = None) -> MagicMock:
    return MagicMock(
        trading=MagicMock(
            crypto=MagicMock(
                symbols=symbols or ["BTC/USDT"],
                exchange="binance",
                timeframes=["1d"],
            )
        ),
        market_context=MagicMock(enabled=False),
    )


class TestRefreshSignalsStaleData:
    async def test_stale_data_skips_symbol_and_sends_alert(self) -> None:
        from trading_bot.strategies.runner import refresh_signals

        stale_bars = _make_bars(stale=True)

        with (
            patch("trading_bot.strategies.runner._load_bars", return_value=stale_bars),
            patch("trading_bot.strategies.runner._freshness_monitor") as mock_monitor,
            # route_signals is lazy-imported from router — patch at source
            patch("trading_bot.execution.router.route_signals", new=AsyncMock()),
            patch("trading_bot.strategies.runner._send_stale_data_alert") as mock_alert,
            patch("trading_bot.strategies.runner.get_settings", return_value=_mock_settings()),
            patch("trading_bot.feature_flags.is_enabled", new=AsyncMock(return_value=True)),
        ):
            mock_monitor.check_freshness.side_effect = DataStalenessError("stale")

            results = await refresh_signals()

        assert results == []
        mock_alert.assert_called_once()

    async def test_fresh_data_computes_signals(self) -> None:
        from trading_bot.strategies.runner import refresh_signals

        fresh_bars = _make_bars(stale=False)
        mock_result = MagicMock()
        mock_result.strategy_id = "sma_crossover"
        mock_result.signal = "BUY"
        mock_result.strength = 0.7
        mock_result.bars_used = 6
        mock_result.model_copy.return_value = mock_result

        mock_strategy = MagicMock(
            strategy_id="sma_crossover",
            compute=MagicMock(return_value=mock_result),
        )

        with (
            patch("trading_bot.strategies.runner._load_bars", return_value=fresh_bars),
            patch("trading_bot.strategies.runner._freshness_monitor") as mock_monitor,
            patch("trading_bot.strategies.runner._STRATEGIES", [mock_strategy]),
            patch("trading_bot.execution.router.route_signals", new=AsyncMock()),
            patch("trading_bot.strategies.runner.get_settings", return_value=_mock_settings()),
            patch("trading_bot.feature_flags.is_enabled", new=AsyncMock(return_value=True)),
        ):
            mock_monitor.check_freshness.return_value = None
            results = await refresh_signals()

        assert len(results) == 1

    async def test_none_market_context_still_routes_signals(self) -> None:
        from trading_bot.strategies.runner import refresh_signals

        fresh_bars = _make_bars(stale=False)
        mock_result = MagicMock()
        mock_result.strategy_id = "sma_crossover"
        mock_result.signal = "HOLD"
        mock_result.strength = 0.0
        mock_result.bars_used = 6
        mock_result.model_copy.return_value = mock_result

        mock_strategy = MagicMock(
            strategy_id="sma_crossover",
            compute=MagicMock(return_value=mock_result),
        )
        route_mock = AsyncMock()

        with (
            patch("trading_bot.strategies.runner._load_bars", return_value=fresh_bars),
            patch("trading_bot.strategies.runner._freshness_monitor") as mock_monitor,
            patch("trading_bot.strategies.runner._STRATEGIES", [mock_strategy]),
            patch("trading_bot.execution.router.route_signals", new=route_mock),
            patch("trading_bot.strategies.runner.get_market_context", return_value=None),
            patch("trading_bot.strategies.runner.get_settings", return_value=_mock_settings()),
            patch("trading_bot.feature_flags.is_enabled", new=AsyncMock(return_value=True)),
        ):
            mock_monitor.check_freshness.return_value = None
            results = await refresh_signals()

        route_mock.assert_called_once()
        assert len(results) == 1

    async def test_missing_bars_skips_symbol(self) -> None:
        from trading_bot.strategies.runner import refresh_signals

        route_mock = AsyncMock()

        with (
            patch("trading_bot.strategies.runner._load_bars", return_value=None),
            patch("trading_bot.execution.router.route_signals", new=route_mock),
            patch("trading_bot.strategies.runner.get_settings", return_value=_mock_settings()),
            patch("trading_bot.feature_flags.is_enabled", new=AsyncMock(return_value=True)),
        ):
            results = await refresh_signals()

        assert results == []

    async def test_strategy_flag_disabled_skips_strategy(self) -> None:
        from trading_bot.strategies.runner import refresh_signals

        fresh_bars = _make_bars(stale=False)
        mock_strategy = MagicMock(
            strategy_id="sma_crossover",
            compute=MagicMock(),
        )
        route_mock = AsyncMock()

        async def _flag(name: str) -> bool:
            return name != "strategy_sma_enabled"

        with (
            patch("trading_bot.strategies.runner._load_bars", return_value=fresh_bars),
            patch("trading_bot.strategies.runner._freshness_monitor") as mock_monitor,
            patch("trading_bot.strategies.runner._STRATEGIES", [mock_strategy]),
            patch("trading_bot.execution.router.route_signals", new=route_mock),
            patch("trading_bot.strategies.runner.get_settings", return_value=_mock_settings()),
            patch("trading_bot.feature_flags.is_enabled", new=AsyncMock(side_effect=_flag)),
        ):
            mock_monitor.check_freshness.return_value = None
            results = await refresh_signals()

        assert results == []
        mock_strategy.compute.assert_not_called()
        route_mock.assert_called_once_with([])
