"""Strategy runner — loads bars from Parquet and runs all registered strategies.

Data flow:
    Parquet files (/data/raw/binance/BTC_USDT/1d/) → DataFrame → strategies → cache

The in-memory cache holds the last computed StrategyResult list.
The APScheduler calls refresh_signals() every 15 minutes.
The dashboard reads get_latest_signals() on each partial reload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from trading_bot.config import get_settings
from trading_bot.market_context import MarketContext, get_market_context
from trading_bot.observability.logging import get_logger
from trading_bot.strategies.base import StrategyResult
from trading_bot.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy

log = get_logger(__name__)

_STRATEGIES = [
    SmaCrossoverStrategy(fast=20, slow=50),
    RsiMeanReversionStrategy(period=14, oversold=30.0, overbought=70.0),
]

_last_results: list[StrategyResult] = []
_last_computed_at: datetime | None = None


def get_latest_signals() -> list[StrategyResult]:
    """Return the most recently computed strategy results (may be empty list)."""
    return list(_last_results)


def get_last_computed_at() -> datetime | None:
    return _last_computed_at


def _load_bars(
    exchange: str = "binance",
    symbol: str = "BTC/USDT",
    timeframe: str = "1d",
    max_bars: int = 200,
) -> pd.DataFrame | None:
    """Load the most recent `max_bars` OHLCV candles from Parquet storage."""
    raw_path = Path(get_settings().storage.raw_path)
    symbol_safe = symbol.replace("/", "_").replace(":", "_")
    parquet_dir = raw_path / exchange / symbol_safe / timeframe

    if not parquet_dir.exists():
        log.warning("parquet_dir_missing", path=str(parquet_dir))
        return None

    files = sorted(parquet_dir.glob("*.parquet"))
    if not files:
        log.warning("no_parquet_files", path=str(parquet_dir))
        return None

    frames: list[pd.DataFrame] = []
    for f in reversed(files):
        try:
            df = pd.read_parquet(f)
            frames.append(df)
            if sum(len(x) for x in frames) >= max_bars:
                break
        except Exception as e:
            log.warning("parquet_read_error", file=str(f), error=str(e))

    if not frames:
        return None

    combined = pd.concat(frames).drop_duplicates(subset=["open_time"]).sort_values("open_time")
    return combined.tail(max_bars).reset_index(drop=True)


async def refresh_signals() -> list[StrategyResult]:
    """Load latest bars and recompute all strategy signals.

    Safe to call concurrently — last writer wins on the cache.
    """
    global _last_results, _last_computed_at

    crypto = get_settings().trading.crypto
    bars = _load_bars(
        exchange=crypto.exchange, symbol=crypto.symbols[0], timeframe=crypto.timeframes[0]
    )
    if bars is None or bars.empty:
        log.warning("signal_refresh_skipped", reason="no bars available")
        return _last_results

    results: list[StrategyResult] = []
    for strategy in _STRATEGIES:
        try:
            result = strategy.compute(bars)
            results.append(result)
            log.info(
                "signal_computed",
                strategy=result.strategy_id,
                signal=result.signal,
                strength=result.strength,
                bars=result.bars_used,
            )
        except Exception as e:
            log.error("strategy_compute_error", strategy=strategy.strategy_id, error=str(e))

    ctx = get_market_context()
    if ctx is not None:
        results = _apply_context(results, ctx)

    _last_results = results
    _last_computed_at = datetime.now(UTC)

    # Route signals to paper exchange (lazy import avoids circular dependency)
    try:
        from trading_bot.execution.router import route_signals

        await route_signals(results)
    except Exception as e:
        log.error("paper_routing_error", error=str(e))

    return results


def _apply_context(results: list[StrategyResult], ctx: MarketContext) -> list[StrategyResult]:
    """Adjust signal strength based on market-wide context.

    Rules (conservative — never flip signal direction, only dampen strength):
      Extreme Fear  + BUY  → cap strength at 0.5 (falling knife risk)
      Extreme Greed + SELL → cap strength at 0.5 (greed can persist)
      Negative funding + BUY → boost strength by 10% (shorts paying = bullish tilt)
      High rates (≥4%) + BUY → reduce strength by 20% (risk-off macro)
      High inflation (≥4%) + BUY → reduce strength by 10%
    """
    adjusted: list[StrategyResult] = []
    for r in results:
        strength = r.strength
        indicators = dict(r.indicators)

        if ctx.fear_greed_value is not None:
            indicators["fear_greed"] = float(ctx.fear_greed_value)
        if ctx.funding_rate is not None:
            indicators["funding_rate"] = ctx.funding_rate
        if ctx.fed_funds_rate is not None:
            indicators["fed_funds_rate"] = ctx.fed_funds_rate

        if r.signal == "BUY":
            if ctx.is_extreme_fear():
                strength = min(strength, 0.5)
            if ctx.is_negative_funding():
                strength = min(strength * 1.1, 1.0)
            if ctx.is_high_rates():
                strength *= 0.8
            if ctx.is_high_inflation():
                strength *= 0.9
        elif r.signal == "SELL":
            if ctx.is_extreme_greed():
                strength = min(strength, 0.5)

        adjusted.append(
            r.model_copy(update={"strength": round(strength, 4), "indicators": indicators})
        )

    return adjusted
