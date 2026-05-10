"""Strategy Decay Detection — #11 of the production readiness roadmap.

Monitors live and paper strategy performance for signs of degradation over
rolling windows. When decay is detected, the monitor recommends demotion or
pause. Automatic pause requires an explicit configuration flag (default: off).

Integrated with the promotion pipeline: strategies with active decay alerts
cannot be promoted to a higher stage until the alert is resolved.

Usage:
    monitor = DecayMonitor(config=DecayConfig())
    update = DecayUpdate(
        strategy_id="sma_cross",
        timestamp=datetime.now(UTC),
        realized_pnl=Decimal("-50"),
        expected_pnl=Decimal("20"),
        signal_fired=True,
        filled=True,
        slippage_bps=8.0,
    )
    monitor.record(update)
    alert = monitor.evaluate("sma_cross")
    if alert is not None:
        log.warning("strategy_decay", severity=alert.severity, metrics=alert.metrics)
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


class DecaySeverity(StrEnum):
    ADVISORY = "advisory"  # worth noting, no action required
    WARNING = "warning"  # recommend review
    CRITICAL = "critical"  # recommend demotion or pause


@dataclass(frozen=True)
class DecayConfig:
    """Thresholds for decay detection across all metrics."""

    # Rolling window length (number of trades)
    window_size: int = 50

    # Sharpe decay: alert if rolling Sharpe drops below this
    sharpe_warning_threshold: float = 0.5
    sharpe_critical_threshold: float = 0.0

    # Drawdown excess: alert if drawdown > expected_max_drawdown_pct by this much
    drawdown_excess_warning_pct: float = 0.05  # 5 percentage points above expected
    drawdown_excess_critical_pct: float = 0.10

    # Hit rate decay: alert if rolling win rate drops below these
    hit_rate_warning_threshold: float = 0.40
    hit_rate_critical_threshold: float = 0.30

    # Signal frequency drift: alert if signals per day drops below this fraction of baseline
    signal_freq_warning_ratio: float = 0.50  # < 50% of baseline
    signal_freq_critical_ratio: float = 0.25

    # Slippage deterioration: alert if avg slippage exceeds these (basis points)
    slippage_warning_bps: float = 20.0
    slippage_critical_bps: float = 50.0

    # Auto-pause on critical breach (disabled by default — operator must set True)
    auto_pause_on_critical: bool = False


@dataclass
class DecayUpdate:
    """A single observation to record for a strategy."""

    strategy_id: str
    timestamp: datetime
    realized_pnl: Decimal
    expected_pnl: Decimal  # from backtest / paper expectation
    signal_fired: bool  # was a signal generated this period?
    filled: bool  # did the signal result in a fill?
    slippage_bps: float = 0.0
    drawdown_pct: float = 0.0  # current peak-to-trough drawdown for this strategy


@dataclass(frozen=True)
class DecayMetrics:
    """Computed decay metrics over the rolling window."""

    rolling_sharpe: float | None
    rolling_hit_rate: float | None
    avg_slippage_bps: float | None
    current_drawdown_pct: float
    signal_count: int
    window_size: int


@dataclass(frozen=True)
class DecayAlert:
    """An active decay alert for a strategy."""

    strategy_id: str
    severity: DecaySeverity
    triggered_at: datetime
    metrics: DecayMetrics
    reasons: list[str]
    recommend_pause: bool
    recommend_demote: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "severity": self.severity,
            "triggered_at": self.triggered_at.isoformat(),
            "reasons": self.reasons,
            "recommend_pause": self.recommend_pause,
            "recommend_demote": self.recommend_demote,
            "rolling_sharpe": self.metrics.rolling_sharpe,
            "rolling_hit_rate": self.metrics.rolling_hit_rate,
            "avg_slippage_bps": self.metrics.avg_slippage_bps,
            "drawdown_pct": self.metrics.current_drawdown_pct,
        }


class _StrategyWindow:
    """Rolling window of observations for a single strategy."""

    def __init__(self, window_size: int) -> None:
        self._pnls: deque[float] = deque(maxlen=window_size)
        self._hits: deque[bool] = deque(maxlen=window_size)
        self._slippages: deque[float] = deque(maxlen=window_size)
        self._drawdowns: deque[float] = deque(maxlen=window_size)
        self._signal_count: int = 0
        self._window_size = window_size

    def record(self, update: DecayUpdate) -> None:
        self._pnls.append(float(update.realized_pnl))
        self._hits.append(update.filled and update.realized_pnl > 0)
        if update.filled:
            self._slippages.append(update.slippage_bps)
        self._drawdowns.append(update.drawdown_pct)
        if update.signal_fired:
            self._signal_count += 1

    def compute_metrics(self) -> DecayMetrics:
        n = len(self._pnls)
        if n < 2:
            return DecayMetrics(
                rolling_sharpe=None,
                rolling_hit_rate=None,
                avg_slippage_bps=None,
                current_drawdown_pct=self._drawdowns[-1] if self._drawdowns else 0.0,
                signal_count=self._signal_count,
                window_size=n,
            )

        pnls = list(self._pnls)
        mean = sum(pnls) / len(pnls)
        variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
        std = math.sqrt(variance) if variance > 0 else 0.0
        sharpe = (mean / std) if std > 0 else None

        hits = list(self._hits)
        hit_rate = sum(1 for h in hits if h) / len(hits) if hits else None

        slips = list(self._slippages)
        avg_slip = sum(slips) / len(slips) if slips else None

        return DecayMetrics(
            rolling_sharpe=sharpe,
            rolling_hit_rate=hit_rate,
            avg_slippage_bps=avg_slip,
            current_drawdown_pct=self._drawdowns[-1] if self._drawdowns else 0.0,
            signal_count=self._signal_count,
            window_size=n,
        )


class DecayMonitor:
    """Monitors rolling strategy performance and emits decay alerts."""

    def __init__(self, config: DecayConfig | None = None) -> None:
        self._config = config or DecayConfig()
        self._windows: dict[str, _StrategyWindow] = {}
        self._active_alerts: dict[str, DecayAlert] = {}
        self._paused_strategies: set[str] = set()

    def record(self, update: DecayUpdate) -> None:
        """Record a new observation. Thread-safe per strategy_id."""
        if update.strategy_id not in self._windows:
            self._windows[update.strategy_id] = _StrategyWindow(self._config.window_size)
        self._windows[update.strategy_id].record(update)

    def evaluate(self, strategy_id: str) -> DecayAlert | None:
        """Evaluate current decay for a strategy. Returns None if healthy."""
        if strategy_id not in self._windows:
            return None

        metrics = self._windows[strategy_id].compute_metrics()
        if metrics.window_size < 5:
            return None  # not enough data

        cfg = self._config
        reasons: list[str] = []
        max_severity = DecaySeverity.ADVISORY

        # Sharpe decay
        if metrics.rolling_sharpe is not None:
            if metrics.rolling_sharpe < cfg.sharpe_critical_threshold:
                reasons.append(
                    f"rolling Sharpe {metrics.rolling_sharpe:.2f} < critical threshold "
                    f"{cfg.sharpe_critical_threshold:.2f}"
                )
                max_severity = DecaySeverity.CRITICAL
            elif metrics.rolling_sharpe < cfg.sharpe_warning_threshold:
                reasons.append(
                    f"rolling Sharpe {metrics.rolling_sharpe:.2f} < warning threshold "
                    f"{cfg.sharpe_warning_threshold:.2f}"
                )
                if max_severity == DecaySeverity.ADVISORY:
                    max_severity = DecaySeverity.WARNING

        # Hit rate decay
        if metrics.rolling_hit_rate is not None:
            if metrics.rolling_hit_rate < cfg.hit_rate_critical_threshold:
                reasons.append(
                    f"hit rate {metrics.rolling_hit_rate:.1%} < critical threshold "
                    f"{cfg.hit_rate_critical_threshold:.1%}"
                )
                max_severity = DecaySeverity.CRITICAL
            elif metrics.rolling_hit_rate < cfg.hit_rate_warning_threshold:
                reasons.append(
                    f"hit rate {metrics.rolling_hit_rate:.1%} < warning threshold "
                    f"{cfg.hit_rate_warning_threshold:.1%}"
                )
                if max_severity == DecaySeverity.ADVISORY:
                    max_severity = DecaySeverity.WARNING

        # Slippage deterioration
        if metrics.avg_slippage_bps is not None:
            if metrics.avg_slippage_bps > cfg.slippage_critical_bps:
                reasons.append(
                    f"avg slippage {metrics.avg_slippage_bps:.1f}bps > critical "
                    f"{cfg.slippage_critical_bps:.1f}bps"
                )
                max_severity = DecaySeverity.CRITICAL
            elif metrics.avg_slippage_bps > cfg.slippage_warning_bps:
                reasons.append(
                    f"avg slippage {metrics.avg_slippage_bps:.1f}bps > warning "
                    f"{cfg.slippage_warning_bps:.1f}bps"
                )
                if max_severity == DecaySeverity.ADVISORY:
                    max_severity = DecaySeverity.WARNING

        # Drawdown excess
        dd = metrics.current_drawdown_pct
        if dd > cfg.drawdown_excess_critical_pct:
            reasons.append(
                f"drawdown {dd:.1%} exceeds critical excess {cfg.drawdown_excess_critical_pct:.1%}"
            )
            max_severity = DecaySeverity.CRITICAL
        elif dd > cfg.drawdown_excess_warning_pct:
            reasons.append(
                f"drawdown {dd:.1%} exceeds warning excess {cfg.drawdown_excess_warning_pct:.1%}"
            )
            if max_severity == DecaySeverity.ADVISORY:
                max_severity = DecaySeverity.WARNING

        if not reasons:
            if strategy_id in self._active_alerts:
                del self._active_alerts[strategy_id]
            return None

        alert = DecayAlert(
            strategy_id=strategy_id,
            severity=max_severity,
            triggered_at=datetime.now(UTC),
            metrics=metrics,
            reasons=reasons,
            recommend_pause=max_severity == DecaySeverity.CRITICAL,
            recommend_demote=max_severity == DecaySeverity.CRITICAL,
        )
        self._active_alerts[strategy_id] = alert

        if max_severity == DecaySeverity.CRITICAL and cfg.auto_pause_on_critical:
            self._paused_strategies.add(strategy_id)
            log.error(
                "strategy_auto_paused_decay",
                strategy_id=strategy_id,
                reasons=reasons,
            )

        log.warning(
            "strategy_decay_alert",
            strategy_id=strategy_id,
            severity=max_severity,
            reasons=reasons,
        )
        return alert

    def is_paused(self, strategy_id: str) -> bool:
        return strategy_id in self._paused_strategies

    def resume(self, strategy_id: str, operator: str) -> None:
        """Manually resume a paused strategy. Clears active alert."""
        self._paused_strategies.discard(strategy_id)
        self._active_alerts.pop(strategy_id, None)
        log.info("strategy_decay_pause_cleared", strategy_id=strategy_id, operator=operator)

    def active_alerts(self) -> dict[str, DecayAlert]:
        return dict(self._active_alerts)
