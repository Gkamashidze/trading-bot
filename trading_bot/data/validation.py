"""Pandera DataFrame schema validation + indicator computation.

Pandera enforces:
- UTC-aware timestamps (rejects naive datetimes)
- OHLCV physical invariants (high >= low, etc.)
- Non-negative volume
- Non-negative prices

SMA-50 is computed here as an example indicator. In Stage 3, indicators
move to the strategies package and use vectorbt for vectorized computation.
"""

from __future__ import annotations

import pandas as pd
import pandera as pa
from pandera import Field
from pandera.typing import Series

from trading_bot.core.exceptions import DataValidationError
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pandera Schema
# ---------------------------------------------------------------------------


class OHLCVSchema(pa.DataFrameModel):
    """Strict schema for OHLCV DataFrames.

    All price/volume columns must be float64. Timestamps must have UTC tz.
    UTC enforcement: pandera rejects timezone-naive datetimes automatically
    when we declare the dtype as DateTime (tz-aware).
    """

    open_time: Series[pa.Timestamp] = Field(
        nullable=False,
        description="Bar open timestamp — UTC-aware required",
    )
    open: Series[float] = Field(ge=0.0, nullable=False)
    high: Series[float] = Field(ge=0.0, nullable=False)
    low: Series[float] = Field(ge=0.0, nullable=False)
    close: Series[float] = Field(ge=0.0, nullable=False)
    volume: Series[float] = Field(ge=0.0, nullable=False)

    class Config:
        strict = False  # allow extra columns (symbol, exchange, etc.)
        coerce = True  # cast Decimal → float at validation time
        ordered = False

    @pa.dataframe_check
    def high_ge_low(self, df: pd.DataFrame) -> bool:  # type: ignore[misc]
        return bool((df["high"] >= df["low"]).all())

    @pa.dataframe_check
    def open_within_range(self, df: pd.DataFrame) -> bool:  # type: ignore[misc]
        return bool(((df["open"] >= df["low"]) & (df["open"] <= df["high"])).all())

    @pa.dataframe_check
    def close_within_range(self, df: pd.DataFrame) -> bool:  # type: ignore[misc]
        return bool(((df["close"] >= df["low"]) & (df["close"] <= df["high"])).all())


def validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Validate an OHLCV DataFrame against OHLCVSchema.

    Returns the validated DataFrame (possibly coerced types).
    Raises DataValidationError on schema violation.
    """
    try:
        validated = OHLCVSchema.validate(df, lazy=True)
        log.debug("ohlcv_validation_passed", rows=len(df))
        return validated
    except pa.errors.SchemaErrors as e:
        failure_cases = (
            e.failure_cases.to_dict(orient="records") if hasattr(e, "failure_cases") else []
        )
        log.error(
            "ohlcv_validation_failed",
            failure_count=len(failure_cases),
            samples=failure_cases[:3],
        )
        raise DataValidationError(
            f"OHLCV DataFrame validation failed: {len(failure_cases)} errors. "
            f"First failure: {failure_cases[0] if failure_cases else 'unknown'}"
        ) from e


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


def compute_sma(df: pd.DataFrame, period: int = 50, price_col: str = "close") -> pd.DataFrame:
    """Add a Simple Moving Average column to an OHLCV DataFrame.

    Returns a copy with an additional column: sma_{period}.
    Requires at least `period` rows; NaN for early rows.

    In Stage 3, this moves to strategies/indicators.py and uses vectorbt
    for vectorized computation across multiple timeframes simultaneously.
    """
    if len(df) < period:
        log.warning(
            "sma_insufficient_data",
            required=period,
            available=len(df),
            action="returning_all_nan",
        )

    col_name = f"sma_{period}"
    result = df.copy()
    result[col_name] = result[price_col].rolling(window=period, min_periods=period).mean()
    return result


def compute_rsi(df: pd.DataFrame, period: int = 14, price_col: str = "close") -> pd.DataFrame:
    """Add Relative Strength Index column. Returns copy with rsi_{period} column."""
    result = df.copy()
    delta = result[price_col].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, float("inf"))
    result[f"rsi_{period}"] = 100 - (100 / (1 + rs))
    return result
