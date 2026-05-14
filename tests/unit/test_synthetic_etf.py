"""Synthetic ETF strategy tests — deterministic forced-trade cycles.

Purpose
-------
Verify that SMA crossover and RSI strategies correctly generate >= 5 buy/sell
signals (and >= 4 completed round-trips) on synthetic OHLCV data, for all
four configured ETF symbols: SPY, QQQ, SOXX, IBIT.

Design
------
- All tests are deterministic (fixed numpy seed + specific sine-wave params).
- No live market data, no real Alpaca API calls.
- Per-symbol strategy params match the values in base.yaml so the same config
  that drives production also drives these tests.
- The BacktestEngine is used with fee_rate=0 and IDEAL fill model so the
  test asserts signal logic, not fill-model randomness.

ETF price assumptions
---------------------
  SPY  ≈ $450  (S&P 500 ETF)
  QQQ  ≈ $370  (Nasdaq 100 ETF)
  SOXX ≈ $190  (Semiconductor ETF)
  IBIT ≈ $35   (iShares Bitcoin Trust ETF)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from trading_bot.backtesting.config import BacktestConfig
from trading_bot.backtesting.engine import BacktestEngine
from trading_bot.backtesting.fill_model import FillModelProfile
from trading_bot.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy

# ---------------------------------------------------------------------------
# Per-symbol strategy parameters (must match base.yaml etf_strategy_params)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _EtfParams:
    symbol: str
    base_price: float
    sma_fast: int
    sma_slow: int
    rsi_period: int
    rsi_oversold: float
    rsi_overbought: float


_ETF_PARAMS: list[_EtfParams] = [
    _EtfParams(
        symbol="SPY",
        base_price=450.0,
        sma_fast=20,
        sma_slow=50,
        rsi_period=14,
        rsi_oversold=32.0,
        rsi_overbought=68.0,
    ),
    _EtfParams(
        symbol="QQQ",
        base_price=370.0,
        sma_fast=15,
        sma_slow=40,
        rsi_period=14,
        rsi_oversold=30.0,
        rsi_overbought=70.0,
    ),
    _EtfParams(
        symbol="SOXX",
        base_price=190.0,
        sma_fast=10,
        sma_slow=30,
        rsi_period=14,
        rsi_oversold=28.0,
        rsi_overbought=72.0,
    ),
    _EtfParams(
        symbol="IBIT",
        base_price=35.0,
        sma_fast=10,
        sma_slow=25,
        rsi_period=14,
        rsi_oversold=25.0,
        rsi_overbought=75.0,
    ),
]


# ---------------------------------------------------------------------------
# Synthetic data generation
# ---------------------------------------------------------------------------


def _make_oscillating_bars(
    symbol: str,
    base_price: float,
    n_bars: int = 500,
    n_cycles: float = 8.0,
    amplitude_pct: float = 0.35,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV bars with a deterministic sine-wave price pattern.

    The sine wave oscillates ±amplitude_pct around base_price with n_cycles
    complete cycles over n_bars bars. This design guarantees:
      - Multiple SMA crossovers (fast SMA leads slow SMA up/down through each cycle).
      - RSI entering both oversold (<30) and overbought (>70) zones each cycle.

    Small normally-distributed noise (0.3% std) is added to prevent degenerate
    flat sequences while keeping the oscillation intact.

    Args:
        symbol: ETF ticker (for DataFrame metadata only).
        base_price: Reference price (e.g., 450 for SPY).
        n_bars: Total number of bars to generate.
        n_cycles: Complete sine cycles across n_bars (more → more signals).
        amplitude_pct: Price swing as fraction of base_price (0.35 = ±35%).
        seed: RNG seed for full reproducibility.

    Returns:
        DataFrame with columns: open_time, open, high, low, close, volume,
        symbol, exchange, timeframe.
    """
    rng = np.random.default_rng(seed)
    t = np.linspace(0, n_cycles * 2 * np.pi, n_bars)
    amplitude = base_price * amplitude_pct

    closes = base_price + amplitude * np.sin(t)
    closes += rng.normal(0, base_price * 0.003, n_bars)  # 0.3% micro-noise
    closes = np.maximum(closes, base_price * 0.05)  # floor at 5% of base

    half_spread = base_price * 0.002
    opens = closes + rng.normal(0, half_spread, n_bars)
    highs = np.maximum(closes, opens) + rng.uniform(0, half_spread * 2, n_bars)
    lows = np.minimum(closes, opens) - rng.uniform(0, half_spread * 2, n_bars)

    dates = pd.date_range(start="2023-01-03", periods=n_bars, freq="B", tz="UTC")

    return pd.DataFrame(
        {
            "open_time": dates,
            "open": opens.tolist(),
            "high": highs.tolist(),
            "low": lows.tolist(),
            "close": closes.tolist(),
            "volume": rng.uniform(1_000_000, 10_000_000, n_bars).tolist(),
            "symbol": symbol,
            "exchange": "alpaca",
            "timeframe": "1d",
        }
    )


# ---------------------------------------------------------------------------
# Backtest config for ETF testing (commission-free, IDEAL fill model)
# ---------------------------------------------------------------------------


_ETF_BACKTEST_CONFIG = BacktestConfig(
    initial_capital=100_000.0,
    fee_rate=0.0,  # Alpaca is commission-free for US equities
    slippage_rate=0.0005,
    position_size_pct=1.0,
    annual_trading_days=252,  # US equity trading days, not crypto 365
    fill_model_profile=FillModelProfile.IDEAL,
    fill_rng_seed=42,
)


# ---------------------------------------------------------------------------
# SMA crossover synthetic tests
# ---------------------------------------------------------------------------


class TestSyntheticSmaCrossover:
    """SMA crossover strategy must generate >= 5 BUY + >= 5 SELL signals
    and produce >= 4 completed round-trip trades for each ETF symbol."""

    @pytest.mark.parametrize("params", _ETF_PARAMS, ids=[p.symbol for p in _ETF_PARAMS])
    def test_min_5_cycles_per_symbol(self, params: _EtfParams) -> None:
        strategy = SmaCrossoverStrategy(fast=params.sma_fast, slow=params.sma_slow)
        bars_df = _make_oscillating_bars(
            symbol=params.symbol,
            base_price=params.base_price,
            n_bars=500,
            n_cycles=8.0,
            amplitude_pct=0.35,
        )

        signals = strategy.backtest_signals(bars_df)
        n_buy = int((signals == "BUY").sum())
        n_sell = int((signals == "SELL").sum())

        assert n_buy >= 5, (
            f"{params.symbol} SMA({params.sma_fast},{params.sma_slow}): "
            f"expected >= 5 BUY signals, got {n_buy}"
        )
        assert n_sell >= 5, (
            f"{params.symbol} SMA({params.sma_fast},{params.sma_slow}): "
            f"expected >= 5 SELL signals, got {n_sell}"
        )

    @pytest.mark.parametrize("params", _ETF_PARAMS, ids=[p.symbol for p in _ETF_PARAMS])
    def test_backtest_min_4_completed_trades(self, params: _EtfParams) -> None:
        strategy = SmaCrossoverStrategy(fast=params.sma_fast, slow=params.sma_slow)
        bars_df = _make_oscillating_bars(
            symbol=params.symbol,
            base_price=params.base_price,
            n_bars=500,
            n_cycles=8.0,
            amplitude_pct=0.35,
        )

        engine = BacktestEngine(config=_ETF_BACKTEST_CONFIG)
        result = engine.run(bars_df, strategy, dataset_snapshot_id="")

        assert result.metrics.total_trades >= 4, (
            f"{params.symbol}: expected >= 4 completed trades, got {result.metrics.total_trades}"
        )

    @pytest.mark.parametrize("params", _ETF_PARAMS, ids=[p.symbol for p in _ETF_PARAMS])
    def test_backtest_reports_valid_metrics(self, params: _EtfParams) -> None:
        strategy = SmaCrossoverStrategy(fast=params.sma_fast, slow=params.sma_slow)
        bars_df = _make_oscillating_bars(
            symbol=params.symbol,
            base_price=params.base_price,
        )
        engine = BacktestEngine(config=_ETF_BACKTEST_CONFIG)
        result = engine.run(bars_df, strategy, dataset_snapshot_id="")

        m = result.metrics
        assert 0.0 <= m.win_rate <= 100.0
        assert m.max_drawdown_pct <= 0.0  # drawdown is negative
        assert result.n_bars == len(bars_df)
        assert result.strategy_id == "sma_crossover"


# ---------------------------------------------------------------------------
# RSI mean reversion synthetic tests
# ---------------------------------------------------------------------------


class TestSyntheticRsiMeanReversion:
    """RSI strategy must generate >= 5 BUY + >= 5 SELL signals for each ETF."""

    @pytest.mark.parametrize("params", _ETF_PARAMS, ids=[p.symbol for p in _ETF_PARAMS])
    def test_min_5_cycles_per_symbol(self, params: _EtfParams) -> None:
        strategy = RsiMeanReversionStrategy(
            period=params.rsi_period,
            oversold=params.rsi_oversold,
            overbought=params.rsi_overbought,
        )
        bars_df = _make_oscillating_bars(
            symbol=params.symbol,
            base_price=params.base_price,
            n_bars=500,
            n_cycles=8.0,
            amplitude_pct=0.35,
        )

        signals = strategy.backtest_signals(bars_df)
        n_buy = int((signals == "BUY").sum())
        n_sell = int((signals == "SELL").sum())

        assert n_buy >= 5, (
            f"{params.symbol} RSI({params.rsi_period}, "
            f"OB={params.rsi_overbought}): expected >= 5 BUY signals, got {n_buy}"
        )
        assert n_sell >= 5, (
            f"{params.symbol} RSI({params.rsi_period}, "
            f"OS={params.rsi_oversold}): expected >= 5 SELL signals, got {n_sell}"
        )

    @pytest.mark.parametrize("params", _ETF_PARAMS, ids=[p.symbol for p in _ETF_PARAMS])
    def test_backtest_produces_completed_trades(self, params: _EtfParams) -> None:
        strategy = RsiMeanReversionStrategy(
            period=params.rsi_period,
            oversold=params.rsi_oversold,
            overbought=params.rsi_overbought,
        )
        bars_df = _make_oscillating_bars(
            symbol=params.symbol,
            base_price=params.base_price,
            n_bars=500,
            n_cycles=8.0,
            amplitude_pct=0.35,
        )
        engine = BacktestEngine(config=_ETF_BACKTEST_CONFIG)
        result = engine.run(bars_df, strategy, dataset_snapshot_id="")

        assert result.metrics.total_trades >= 4, (
            f"{params.symbol} RSI backtest: expected >= 4 trades, got {result.metrics.total_trades}"
        )


# ---------------------------------------------------------------------------
# Cross-symbol combined report (informational, not assertion-heavy)
# ---------------------------------------------------------------------------


class TestSyntheticCombinedReport:
    """Run all four symbols and collect a combined summary.

    This test always passes — it documents the synthetic test results in the
    pytest output so the team can track strategy behaviour across symbols.
    """

    def test_combined_sma_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        print("\n── Synthetic SMA Crossover Backtest Report ──────────────────")
        for params in _ETF_PARAMS:
            strategy = SmaCrossoverStrategy(fast=params.sma_fast, slow=params.sma_slow)
            bars_df = _make_oscillating_bars(
                symbol=params.symbol,
                base_price=params.base_price,
            )
            engine = BacktestEngine(config=_ETF_BACKTEST_CONFIG)
            result = engine.run(bars_df, strategy, dataset_snapshot_id="")

            signals = strategy.backtest_signals(bars_df)
            n_buy = int((signals == "BUY").sum())
            n_sell = int((signals == "SELL").sum())

            print(
                f"  {params.symbol:5s}  buys={n_buy:2d}  sells={n_sell:2d}  "
                f"trades={result.metrics.total_trades:2d}  "
                f"win%={result.metrics.win_rate:.0f}  "
                f"return%={result.metrics.total_return_pct:+.1f}  "
                f"maxDD%={result.metrics.max_drawdown_pct:.1f}"
            )
        print("─────────────────────────────────────────────────────────────")

    def test_combined_rsi_report(self, capsys: pytest.CaptureFixture[str]) -> None:
        print("\n── Synthetic RSI Mean Reversion Backtest Report ─────────────")
        for params in _ETF_PARAMS:
            strategy = RsiMeanReversionStrategy(
                period=params.rsi_period,
                oversold=params.rsi_oversold,
                overbought=params.rsi_overbought,
            )
            bars_df = _make_oscillating_bars(
                symbol=params.symbol,
                base_price=params.base_price,
            )
            engine = BacktestEngine(config=_ETF_BACKTEST_CONFIG)
            result = engine.run(bars_df, strategy, dataset_snapshot_id="")

            signals = strategy.backtest_signals(bars_df)
            n_buy = int((signals == "BUY").sum())
            n_sell = int((signals == "SELL").sum())

            print(
                f"  {params.symbol:5s}  buys={n_buy:2d}  sells={n_sell:2d}  "
                f"trades={result.metrics.total_trades:2d}  "
                f"win%={result.metrics.win_rate:.0f}  "
                f"return%={result.metrics.total_return_pct:+.1f}  "
                f"maxDD%={result.metrics.max_drawdown_pct:.1f}"
            )
        print("─────────────────────────────────────────────────────────────")
