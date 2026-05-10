"""Tests for monitoring/decay.py — StrategyDecayMonitor."""

from datetime import UTC, datetime
from decimal import Decimal

from trading_bot.monitoring.decay import (
    DecayConfig,
    DecayMonitor,
    DecaySeverity,
    DecayUpdate,
)


def _update(
    strategy_id: str = "sma",
    pnl: float = 1.0,
    hit: bool = True,
    slippage_bps: float = 5.0,
    drawdown_pct: float = 0.01,
) -> DecayUpdate:
    return DecayUpdate(
        strategy_id=strategy_id,
        timestamp=datetime.now(UTC),
        realized_pnl=Decimal(str(pnl)),
        expected_pnl=Decimal("1"),
        signal_fired=True,
        filled=hit,
        slippage_bps=slippage_bps,
        drawdown_pct=drawdown_pct,
    )


class TestDecayMonitor:
    def setup_method(self) -> None:
        self.cfg = DecayConfig(
            window_size=10,
            sharpe_warning_threshold=0.5,
            sharpe_critical_threshold=0.0,
            hit_rate_warning_threshold=0.4,
            hit_rate_critical_threshold=0.3,
            slippage_warning_bps=20.0,
            slippage_critical_bps=50.0,
            drawdown_excess_warning_pct=0.05,
            drawdown_excess_critical_pct=0.10,
        )
        self.monitor = DecayMonitor(config=self.cfg)

    def _populate(self, n: int = 10, pnl: float = 1.0, hit: bool = True) -> None:
        for _ in range(n):
            self.monitor.record(_update(pnl=pnl, hit=hit))

    def test_no_alert_on_healthy_strategy(self) -> None:
        self._populate(10, pnl=1.0, hit=True)
        alert = self.monitor.evaluate("sma")
        assert alert is None

    def test_no_alert_insufficient_data(self) -> None:
        for _ in range(3):
            self.monitor.record(_update())
        alert = self.monitor.evaluate("sma")
        assert alert is None

    def test_unknown_strategy_returns_none(self) -> None:
        assert self.monitor.evaluate("nonexistent") is None

    def test_low_hit_rate_triggers_warning(self) -> None:
        for _ in range(10):
            self.monitor.record(_update(pnl=-1.0, hit=False))
        alert = self.monitor.evaluate("sma")
        assert alert is not None
        assert alert.severity in (DecaySeverity.WARNING, DecaySeverity.CRITICAL)

    def test_high_slippage_triggers_warning(self) -> None:
        for _ in range(10):
            self.monitor.record(_update(slippage_bps=30.0))
        alert = self.monitor.evaluate("sma")
        assert alert is not None

    def test_critical_slippage_triggers_critical(self) -> None:
        for _ in range(10):
            self.monitor.record(_update(slippage_bps=60.0))
        alert = self.monitor.evaluate("sma")
        assert alert is not None
        assert alert.severity == DecaySeverity.CRITICAL

    def test_excessive_drawdown_triggers_alert(self) -> None:
        for _ in range(10):
            self.monitor.record(_update(drawdown_pct=0.15))
        alert = self.monitor.evaluate("sma")
        assert alert is not None
        assert alert.severity == DecaySeverity.CRITICAL

    def test_alert_has_reasons(self) -> None:
        for _ in range(10):
            self.monitor.record(_update(pnl=-1.0, hit=False, slippage_bps=60.0))
        alert = self.monitor.evaluate("sma")
        assert alert is not None
        assert len(alert.reasons) > 0

    def test_auto_pause_disabled_by_default(self) -> None:
        for _ in range(10):
            self.monitor.record(_update(pnl=-10.0, hit=False, slippage_bps=100.0))
        self.monitor.evaluate("sma")
        assert not self.monitor.is_paused("sma")

    def test_auto_pause_when_enabled(self) -> None:
        cfg = DecayConfig(
            window_size=10,
            slippage_critical_bps=50.0,
            auto_pause_on_critical=True,
        )
        monitor = DecayMonitor(config=cfg)
        for _ in range(10):
            monitor.record(_update(slippage_bps=100.0))
        monitor.evaluate("sma")
        assert monitor.is_paused("sma")

    def test_resume_clears_pause_and_alert(self) -> None:
        cfg = DecayConfig(window_size=10, slippage_critical_bps=50.0, auto_pause_on_critical=True)
        monitor = DecayMonitor(config=cfg)
        for _ in range(10):
            monitor.record(_update(slippage_bps=100.0))
        monitor.evaluate("sma")
        monitor.resume("sma", "alice")
        assert not monitor.is_paused("sma")
        assert "sma" not in monitor.active_alerts()

    def test_alert_to_dict_has_fields(self) -> None:
        for _ in range(10):
            self.monitor.record(_update(pnl=-1.0, hit=False, slippage_bps=60.0))
        alert = self.monitor.evaluate("sma")
        assert alert is not None
        d = alert.to_dict()
        assert "severity" in d
        assert "reasons" in d
        assert "strategy_id" in d
