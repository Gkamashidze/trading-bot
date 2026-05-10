"""Unit tests for data_quality/monitor.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from trading_bot.core.exceptions import DataAnomalyError, DataStalenessError
from trading_bot.data_quality.monitor import DataQualityMonitor


def _ts(offset_seconds: float = 0) -> pd.Timestamp:
    """Return a UTC-aware Timestamp offset from now."""
    dt = datetime.now(UTC) - timedelta(seconds=offset_seconds)
    return pd.Timestamp(dt)


class TestFreshnessCheck:
    def _monitor(self) -> DataQualityMonitor:
        return DataQualityMonitor(freshness_multiplier=2.0)

    def test_fresh_1d_bar_passes(self) -> None:
        monitor = self._monitor()
        # 1d interval → threshold = 172800s; bar 1h old → fresh
        last_bar = _ts(offset_seconds=3600)

        with patch("trading_bot.data_quality.monitor.DATA_FEED_STALENESS") as mock_gauge:
            mock_gauge.labels.return_value = MagicMock()
            monitor.check_freshness("binance", "BTC/USDT", "1d", last_bar)

    def test_stale_1d_bar_raises(self) -> None:
        monitor = self._monitor()
        # 1d interval → threshold = 172800s; bar 3 days old → stale
        last_bar = _ts(offset_seconds=3 * 86400)

        with patch("trading_bot.data_quality.monitor.DATA_FEED_STALENESS") as mock_gauge:
            mock_gauge.labels.return_value = MagicMock()
            with pytest.raises(DataStalenessError, match="stale"):
                monitor.check_freshness("binance", "BTC/USDT", "1d", last_bar)

    def test_stale_1h_bar_raises(self) -> None:
        monitor = self._monitor()
        # 1h interval → threshold = 7200s; bar 4h old → stale
        last_bar = _ts(offset_seconds=4 * 3600)

        with patch("trading_bot.data_quality.monitor.DATA_FEED_STALENESS") as mock_gauge:
            mock_gauge.labels.return_value = MagicMock()
            with pytest.raises(DataStalenessError):
                monitor.check_freshness("binance", "BTC/USDT", "1h", last_bar)

    def test_fresh_1h_bar_passes(self) -> None:
        monitor = self._monitor()
        # 1h interval → threshold = 7200s; bar 30 min old → fresh
        last_bar = _ts(offset_seconds=1800)

        with patch("trading_bot.data_quality.monitor.DATA_FEED_STALENESS") as mock_gauge:
            mock_gauge.labels.return_value = MagicMock()
            monitor.check_freshness("binance", "BTC/USDT", "1h", last_bar)

    def test_unknown_timeframe_defaults_to_1h_threshold(self) -> None:
        monitor = self._monitor()
        # unknown timeframe defaults to 3600s → threshold = 7200s
        last_bar = _ts(offset_seconds=3600)

        with patch("trading_bot.data_quality.monitor.DATA_FEED_STALENESS") as mock_gauge:
            mock_gauge.labels.return_value = MagicMock()
            monitor.check_freshness("binance", "BTC/USDT", "3d", last_bar)

    def test_prometheus_gauge_always_updated(self) -> None:
        monitor = self._monitor()
        last_bar = _ts(offset_seconds=3600)

        with patch("trading_bot.data_quality.monitor.DATA_FEED_STALENESS") as mock_gauge:
            label_mock = MagicMock()
            mock_gauge.labels.return_value = label_mock
            monitor.check_freshness("binance", "BTC/USDT", "1d", last_bar)

        mock_gauge.labels.assert_called_once_with(
            exchange="binance", symbol="BTC/USDT", timeframe="1d"
        )
        label_mock.set.assert_called_once()


class TestAnomalyDetection:
    def _normal_df(self, n: int = 50) -> pd.DataFrame:
        prices = [50000.0 * (1 + 0.001 * i) for i in range(n)]
        return pd.DataFrame({"close": prices})

    def _df_with_spike(self) -> pd.DataFrame:
        prices = [50000.0] * 50
        prices[40] = 500000.0  # 10x spike → extreme z-score
        return pd.DataFrame({"close": prices})

    def test_normal_bars_no_anomaly(self) -> None:
        monitor = DataQualityMonitor(zscore_threshold=5.0)
        df = self._normal_df()

        with patch("trading_bot.data_quality.monitor.DATA_ANOMALIES_DETECTED"):
            result = monitor.detect_anomalies(df, "binance", "BTC/USDT")

        assert "anomaly" in result.columns
        assert result["anomaly"].sum() == 0

    def test_price_spike_flagged_as_anomaly(self) -> None:
        monitor = DataQualityMonitor(zscore_threshold=5.0)
        df = self._df_with_spike()

        with patch("trading_bot.data_quality.monitor.DATA_ANOMALIES_DETECTED") as mock_counter:
            mock_counter.labels.return_value = MagicMock()
            result = monitor.detect_anomalies(df, "binance", "BTC/USDT")

        assert result["anomaly"].sum() > 0

    def test_short_df_returns_false_anomalies(self) -> None:
        monitor = DataQualityMonitor()
        df = pd.DataFrame({"close": [50000.0]})

        with patch("trading_bot.data_quality.monitor.DATA_ANOMALIES_DETECTED"):
            result = monitor.detect_anomalies(df, "binance", "BTC/USDT")

        assert result["anomaly"].all() == False  # noqa: E712

    def test_anomaly_does_not_remove_rows(self) -> None:
        monitor = DataQualityMonitor(zscore_threshold=5.0)
        df = self._df_with_spike()

        with patch("trading_bot.data_quality.monitor.DATA_ANOMALIES_DETECTED") as mock_counter:
            mock_counter.labels.return_value = MagicMock()
            result = monitor.detect_anomalies(df, "binance", "BTC/USDT")

        assert len(result) == len(df)


class TestTickValidation:
    def test_valid_tick_passes(self) -> None:
        monitor = DataQualityMonitor()
        with patch("trading_bot.data_quality.monitor.DATA_ANOMALIES_DETECTED"):
            monitor.validate_tick("binance", "BTC/USDT", price=50000.0, volume=1.5)

    def test_zero_price_raises(self) -> None:
        monitor = DataQualityMonitor()
        with patch("trading_bot.data_quality.monitor.DATA_ANOMALIES_DETECTED") as mock_counter:
            mock_counter.labels.return_value = MagicMock()
            with pytest.raises(DataAnomalyError, match="price"):
                monitor.validate_tick("binance", "BTC/USDT", price=0.0, volume=1.0)

    def test_negative_price_raises(self) -> None:
        monitor = DataQualityMonitor()
        with patch("trading_bot.data_quality.monitor.DATA_ANOMALIES_DETECTED") as mock_counter:
            mock_counter.labels.return_value = MagicMock()
            with pytest.raises(DataAnomalyError):
                monitor.validate_tick("binance", "BTC/USDT", price=-100.0, volume=1.0)

    def test_negative_volume_raises(self) -> None:
        monitor = DataQualityMonitor()
        with patch("trading_bot.data_quality.monitor.DATA_ANOMALIES_DETECTED") as mock_counter:
            mock_counter.labels.return_value = MagicMock()
            with pytest.raises(DataAnomalyError, match="volume"):
                monitor.validate_tick("binance", "BTC/USDT", price=50000.0, volume=-1.0)

    def test_zero_volume_passes(self) -> None:
        monitor = DataQualityMonitor()
        with patch("trading_bot.data_quality.monitor.DATA_ANOMALIES_DETECTED"):
            monitor.validate_tick("binance", "BTC/USDT", price=50000.0, volume=0.0)
