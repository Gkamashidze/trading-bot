"""Data quality monitor — freshness and anomaly detection.

Freshness check:
- Each (exchange, symbol, timeframe) has an expected update interval
- If last_update > N x interval → DataStalenessEvent

Anomaly detection:
- Compute rolling z-score of log-returns
- If |z-score| > threshold → DataAnomalyError (bar flagged, not deleted)
- Anomalous bars are quarantined in data/raw/.../quarantine/ for audit
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from trading_bot.core.exceptions import DataAnomalyError, DataStalenessError
from trading_bot.observability.logging import get_logger
from trading_bot.observability.metrics import DATA_ANOMALIES_DETECTED, DATA_FEED_STALENESS
from trading_bot.utils.time_sync import utc_now

log = get_logger(__name__)

_TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


class DataQualityMonitor:
    """Monitor for data freshness and anomaly detection."""

    def __init__(
        self,
        freshness_multiplier: float = 2.0,
        zscore_threshold: float = 5.0,
    ) -> None:
        self._freshness_multiplier = freshness_multiplier
        self._zscore_threshold = zscore_threshold

    def check_freshness(
        self,
        exchange: str,
        symbol: str,
        timeframe: str,
        last_bar_time: pd.Timestamp,
    ) -> None:
        """Raise DataStalenessError if data is stale beyond the threshold.

        Updates Prometheus gauge regardless of outcome.
        """
        now = utc_now()
        staleness_seconds = (now - last_bar_time.to_pydatetime()).total_seconds()

        DATA_FEED_STALENESS.labels(
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe,
        ).set(staleness_seconds)

        expected_interval = _TIMEFRAME_SECONDS.get(timeframe, 3600)
        threshold = expected_interval * self._freshness_multiplier

        if staleness_seconds > threshold:
            log.warning(
                "data_stale",
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                staleness_seconds=staleness_seconds,
                threshold_seconds=threshold,
            )
            raise DataStalenessError(
                f"Data for {exchange}/{symbol}/{timeframe} is stale: "
                f"{staleness_seconds:.0f}s > threshold {threshold:.0f}s"
            )

    def detect_anomalies(
        self,
        df: pd.DataFrame,
        exchange: str,
        symbol: str,
        window: int = 100,
    ) -> pd.DataFrame:
        """Compute rolling z-score of log-returns and flag anomalous bars.

        Returns DataFrame with added 'anomaly' boolean column.
        Anomalous bars are NOT removed — they're flagged for audit.
        The caller decides whether to quarantine or continue with the data.
        """
        result = df.copy()

        if len(result) < 2:
            result["zscore"] = np.nan
            result["anomaly"] = False
            return result

        close: pd.Series = result["close"]
        log_returns: pd.Series = pd.Series(np.log(close / close.shift(1)))
        rolling_mean = log_returns.rolling(window=window, min_periods=10).mean()
        rolling_std = log_returns.rolling(window=window, min_periods=10).std()

        zscore = (log_returns - rolling_mean) / rolling_std.replace(0, np.nan)
        result["zscore"] = zscore
        result["anomaly"] = zscore.abs() > self._zscore_threshold

        n_anomalies = int(result["anomaly"].sum())
        if n_anomalies > 0:
            DATA_ANOMALIES_DETECTED.labels(
                exchange=exchange,
                symbol=symbol,
                anomaly_type="zscore_breach",
            ).inc(n_anomalies)

            log.warning(
                "data_anomalies_detected",
                exchange=exchange,
                symbol=symbol,
                count=n_anomalies,
                threshold=self._zscore_threshold,
                action="flagged_not_removed",
            )

        return result

    def validate_tick(
        self,
        exchange: str,
        symbol: str,
        price: float,
        volume: float,
    ) -> None:
        """Validate a single tick for basic sanity (price > 0, volume >= 0)."""
        if price <= 0:
            DATA_ANOMALIES_DETECTED.labels(
                exchange=exchange,
                symbol=symbol,
                anomaly_type="negative_price",
            ).inc()
            raise DataAnomalyError(f"Tick anomaly: price={price} <= 0 for {exchange}/{symbol}")
        if volume < 0:
            DATA_ANOMALIES_DETECTED.labels(
                exchange=exchange,
                symbol=symbol,
                anomaly_type="negative_volume",
            ).inc()
            raise DataAnomalyError(f"Tick anomaly: volume={volume} < 0 for {exchange}/{symbol}")
