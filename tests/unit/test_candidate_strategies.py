"""Unit tests for the research candidate strategies.

Verifies each produces only valid BUY/SELL/HOLD signals aligned to the bars,
and basic parameter validation. These are the candidates evaluated by the
walk-forward harness (none beat buy-and-hold — see docs/strategies/backtest_reports/).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from trading_bot.strategies.candidates import (
    DonchianBreakoutStrategy,
    MacdStrategy,
    TrendFilterStrategy,
)


def _bars(n: int = 600, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.exp(rng.normal(0.0003, 0.01, n).cumsum())
    open_ = np.concatenate([[100.0], close[:-1]])
    t0 = datetime(2023, 1, 1, tzinfo=UTC)
    return pd.DataFrame(
        {
            "open_time": [t0 + timedelta(hours=i) for i in range(n)],
            "open": open_,
            "high": np.maximum(open_, close) * 1.002,
            "low": np.minimum(open_, close) * 0.998,
            "close": close,
            "volume": rng.uniform(10, 100, n),
        }
    )


_VALID = {"BUY", "SELL", "HOLD"}


class TestCandidateSignals:
    @pytest.mark.parametrize(
        "strategy",
        [
            TrendFilterStrategy(period=240),
            DonchianBreakoutStrategy(entry=120, exit_period=60),
            MacdStrategy(fast=12, slow=26, signal=9),
        ],
    )
    def test_signals_valid_and_aligned(self, strategy: object) -> None:
        bars = _bars()
        signals = strategy.backtest_signals(bars)  # type: ignore[attr-defined]
        assert len(signals) == len(bars)
        assert set(signals.unique()).issubset(_VALID)
        # a trending series should generate at least one entry
        assert (signals == "BUY").any()


class TestValidation:
    def test_macd_rejects_fast_ge_slow(self) -> None:
        with pytest.raises(ValueError, match="must be <"):
            MacdStrategy(fast=52, slow=26)

    def test_trend_filter_min_bars(self) -> None:
        assert TrendFilterStrategy(period=240).min_bars_required == 242
