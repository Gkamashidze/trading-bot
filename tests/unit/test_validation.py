"""Unit tests for OHLCV Pandera validation and SMA indicator."""

from __future__ import annotations

import pandas as pd
import pytest

from trading_bot.core.exceptions import DataValidationError
from trading_bot.data.validation import compute_sma, validate_ohlcv


class TestValidateOHLCV:
    def test_valid_df_passes(self, sample_ohlcv_df: pd.DataFrame) -> None:
        validated = validate_ohlcv(sample_ohlcv_df)
        assert len(validated) == 100

    def test_negative_close_rejected(self, sample_ohlcv_df: pd.DataFrame) -> None:
        bad = sample_ohlcv_df.copy()
        bad.loc[0, "close"] = -1.0
        with pytest.raises(DataValidationError):
            validate_ohlcv(bad)

    def test_high_less_than_low_rejected(self, sample_ohlcv_df: pd.DataFrame) -> None:
        bad = sample_ohlcv_df.copy()
        bad.loc[0, "high"] = bad.loc[0, "low"] - 100  # intentional violation
        with pytest.raises(DataValidationError):
            validate_ohlcv(bad)


class TestComputeSMA:
    def test_sma_50_column_added(self, sample_ohlcv_df: pd.DataFrame) -> None:
        result = compute_sma(sample_ohlcv_df, period=50)
        assert "sma_50" in result.columns

    def test_first_49_rows_are_nan(self, sample_ohlcv_df: pd.DataFrame) -> None:
        result = compute_sma(sample_ohlcv_df, period=50)
        assert result["sma_50"].iloc[:49].isna().all()

    def test_row_50_is_not_nan(self, sample_ohlcv_df: pd.DataFrame) -> None:
        result = compute_sma(sample_ohlcv_df, period=50)
        assert pd.notna(result["sma_50"].iloc[49])

    def test_sma_is_mean_of_preceding_window(self, sample_ohlcv_df: pd.DataFrame) -> None:
        result = compute_sma(sample_ohlcv_df, period=10)
        expected = sample_ohlcv_df["close"].iloc[0:10].mean()
        assert abs(result["sma_10"].iloc[9] - expected) < 1e-6

    def test_original_df_unchanged(self, sample_ohlcv_df: pd.DataFrame) -> None:
        original_cols = list(sample_ohlcv_df.columns)
        compute_sma(sample_ohlcv_df, period=50)
        assert list(sample_ohlcv_df.columns) == original_cols
