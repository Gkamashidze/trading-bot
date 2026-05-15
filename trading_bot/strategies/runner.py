"""Strategy runner — loads bars from Parquet and runs all registered strategies.

Data flow:
    Parquet files (/data/raw/binance/<SYMBOL>/<TF>/) → DataFrame → strategies → cache

The in-memory cache holds the last computed StrategyResult list (all symbols).
The APScheduler calls refresh_signals() every 15 minutes.
The dashboard reads get_latest_signals() on each partial reload.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from trading_bot.config import get_settings
from trading_bot.core.exceptions import DataStalenessError
from trading_bot.data_quality.monitor import DataQualityMonitor
from trading_bot.market_context import MarketContext, get_market_context
from trading_bot.observability.logging import get_logger
from trading_bot.promotion.pipeline import PromotionTier, register_strategy
from trading_bot.strategies.base import StrategyResult
from trading_bot.strategies.rsi_mean_reversion import RsiMeanReversionStrategy
from trading_bot.strategies.sma_crossover import SmaCrossoverStrategy

log = get_logger(__name__)

_STRATEGIES = [
    SmaCrossoverStrategy(fast=20, slow=50),
    RsiMeanReversionStrategy(period=14, oversold=30.0, overbought=70.0),
]
_freshness_monitor = DataQualityMonitor()

# Register all strategies in the promotion pipeline on module load
for _s in _STRATEGIES:
    register_strategy(_s.strategy_id, tier=PromotionTier.PAPER)

_last_results: list[StrategyResult] = []
_last_computed_at: datetime | None = None

_STRATEGY_FLAGS = {
    "sma_crossover": "strategy_sma_enabled",
    "rsi_mean_reversion": "strategy_rsi_enabled",
}


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
    """Load latest bars for every configured symbol and recompute all strategy signals.

    Safe to call concurrently — last writer wins on the cache.
    """
    global _last_results, _last_computed_at

    crypto = get_settings().trading.crypto
    ctx = get_market_context()
    all_results: list[StrategyResult] = []

    from trading_bot.asset_universe import get_asset_registry
    from trading_bot.feature_flags import is_enabled

    registry = get_asset_registry()

    for symbol in crypto.symbols:
        spec = registry.get(symbol)
        if spec is None or not registry.is_data_eligible(symbol):
            log.info("signal_refresh_skipped_asset_disabled", symbol=symbol)
            continue
        if spec.feature_flag and not await is_enabled(spec.feature_flag):
            log.info(
                "signal_refresh_skipped_asset_flag",
                symbol=symbol,
                feature_flag=spec.feature_flag,
            )
            continue
        bars = _load_bars(exchange=crypto.exchange, symbol=symbol, timeframe=crypto.timeframes[0])
        if bars is None or bars.empty:
            log.warning("signal_refresh_skipped", symbol=symbol, reason="no bars available")
            continue

        # Freshness gate — skip stale data rather than trade on bad inputs
        last_bar_ts = bars.iloc[-1]["open_time"]
        if not isinstance(last_bar_ts, pd.Timestamp):
            last_bar_ts = pd.Timestamp(last_bar_ts)
        try:
            _freshness_monitor.check_freshness(
                exchange=crypto.exchange,
                symbol=symbol,
                timeframe=crypto.timeframes[0],
                last_bar_time=last_bar_ts,
            )
        except DataStalenessError as e:
            log.error("signal_refresh_stale_data", symbol=symbol, error=str(e))
            _send_stale_data_alert(symbol, str(e))
            continue

        for strategy in _STRATEGIES:
            flag_name = _STRATEGY_FLAGS.get(strategy.strategy_id)
            if flag_name and not await is_enabled(flag_name):
                log.debug(
                    "strategy_skipped_feature_flag",
                    strategy=strategy.strategy_id,
                    flag=flag_name,
                )
                continue
            if spec.enabled_strategies and strategy.strategy_id not in spec.enabled_strategies:
                log.debug(
                    "strategy_skipped_asset_allowlist",
                    symbol=symbol,
                    strategy=strategy.strategy_id,
                )
                continue
            try:
                result = strategy.compute(bars)
                result = result.model_copy(update={"symbol": symbol})
                all_results.append(result)
                log.info(
                    "signal_computed",
                    symbol=symbol,
                    strategy=result.strategy_id,
                    signal=result.signal,
                    strength=result.strength,
                    bars=result.bars_used,
                )
            except Exception as e:
                log.error(
                    "strategy_compute_error",
                    symbol=symbol,
                    strategy=strategy.strategy_id,
                    error=str(e),
                )

    if ctx is not None:
        all_results = _apply_context(all_results, ctx)

    _last_results = all_results
    _last_computed_at = datetime.now(UTC)

    # Route signals to paper exchange (lazy import avoids circular dependency)
    try:
        from trading_bot.execution.router import route_signals

        await route_signals(all_results)
    except Exception as e:
        log.error("paper_routing_error", error=str(e))

    return all_results


def _apply_context(results: list[StrategyResult], ctx: MarketContext) -> list[StrategyResult]:
    """Adjust signal strength based on market-wide context.

    Rules (conservative — never flip signal direction, only dampen strength):
      Extreme Fear  + BUY  → cap strength at 0.5 (falling knife risk)
      Extreme Greed + SELL → cap strength at 0.5 (greed can persist)
      Negative funding + BUY → dampen strength by 10% (crowded shorts = uncertain direction)
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
                strength *= 0.9
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


def _send_stale_data_alert(symbol: str, detail: str) -> None:
    """Fire a Telegram alert when data is stale (non-blocking, best-effort)."""
    import asyncio

    from trading_bot.alerts.telegram import AlertLevel, TelegramAlerter

    alerter = TelegramAlerter.from_env_optional()
    if alerter is None:
        return

    async def _send() -> None:
        await alerter.send(
            AlertLevel.ERROR,
            f"Stale data — signal skipped: {symbol}",
            detail=detail[:400],
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(_send())  # noqa: RUF006
    except Exception:  # noqa: S110
        pass
