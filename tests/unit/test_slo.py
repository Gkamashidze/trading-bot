"""Unit tests for SLO/SLI monitoring (Feature #9)."""

from __future__ import annotations

import pytest

from trading_bot.monitoring.slo import (
    DEFAULT_SLO_TARGETS,
    AlertRoutingPolicy,
    AlertSeverity,
    SLIName,
    SLOMonitor,
    get_slo_monitor,
)


def _monitor() -> SLOMonitor:
    return SLOMonitor()


class TestSLOTarget:
    def test_no_breach_below_warning(self) -> None:
        target = DEFAULT_SLO_TARGETS[SLIName.WEBSOCKET_FRESHNESS]
        assert target.severity_for(10.0) is None  # 10 s < 30 s warning

    def test_warning_at_threshold(self) -> None:
        target = DEFAULT_SLO_TARGETS[SLIName.WEBSOCKET_FRESHNESS]
        assert target.severity_for(30.0) == AlertSeverity.WARNING

    def test_critical_at_threshold(self) -> None:
        target = DEFAULT_SLO_TARGETS[SLIName.WEBSOCKET_FRESHNESS]
        assert target.severity_for(120.0) == AlertSeverity.CRITICAL

    def test_critical_above_threshold(self) -> None:
        target = DEFAULT_SLO_TARGETS[SLIName.ORDER_LATENCY]
        assert target.severity_for(5000.0) == AlertSeverity.CRITICAL

    def test_all_default_targets_have_runbook(self) -> None:
        for target in DEFAULT_SLO_TARGETS.values():
            assert target.runbook_url != "", f"{target.sli} missing runbook_url"


class TestSLOMonitor:
    def test_healthy_measurement_returns_none(self) -> None:
        m = _monitor()
        result = m.record(SLIName.WEBSOCKET_FRESHNESS, 5.0)
        assert result is None

    def test_warning_breach_fires_alert(self) -> None:
        m = _monitor()
        alert = m.record(SLIName.WEBSOCKET_FRESHNESS, 60.0)
        assert alert is not None
        assert alert.severity == AlertSeverity.WARNING
        assert alert.sli == SLIName.WEBSOCKET_FRESHNESS

    def test_critical_breach_fires_alert(self) -> None:
        m = _monitor()
        alert = m.record(SLIName.WEBSOCKET_FRESHNESS, 200.0)
        assert alert is not None
        assert alert.severity == AlertSeverity.CRITICAL

    def test_alert_is_in_active_alerts(self) -> None:
        m = _monitor()
        alert = m.record(SLIName.ORDER_LATENCY, 1000.0)
        assert alert is not None
        active = m.active_alerts()
        assert any(a.alert_id == alert.alert_id for a in active)

    def test_recovery_auto_clears_unacknowledged_alert(self) -> None:
        m = _monitor()
        m.record(SLIName.WEBSOCKET_FRESHNESS, 60.0)  # fire
        m.record(SLIName.WEBSOCKET_FRESHNESS, 5.0)  # recover
        assert m.active_alerts(SLIName.WEBSOCKET_FRESHNESS) == []

    def test_acknowledged_alert_not_auto_cleared(self) -> None:
        m = _monitor()
        alert = m.record(SLIName.WEBSOCKET_FRESHNESS, 60.0)
        assert alert is not None
        m.acknowledge(alert.alert_id, operator="ops")
        m.record(SLIName.WEBSOCKET_FRESHNESS, 5.0)  # would normally clear
        active = m.active_alerts(SLIName.WEBSOCKET_FRESHNESS)
        # Acknowledged alert stays until explicitly removed
        assert any(a.alert_id == alert.alert_id for a in active)

    def test_acknowledge_sets_fields(self) -> None:
        m = _monitor()
        alert = m.record(SLIName.RECONCILIATION_LAG, 600.0)
        assert alert is not None
        acked = m.acknowledge(alert.alert_id, operator="alice", notes="investigating")
        assert acked.acknowledged is True
        assert acked.acknowledged_by == "alice"
        assert acked.notes == "investigating"
        assert acked.acknowledged_at is not None

    def test_acknowledge_unknown_raises_keyerror(self) -> None:
        m = _monitor()
        with pytest.raises(KeyError):
            m.acknowledge("unknown-id", operator="ops")

    def test_alert_history_preserved_after_clear(self) -> None:
        m = _monitor()
        m.record(SLIName.WEBSOCKET_FRESHNESS, 60.0)  # fire
        m.record(SLIName.WEBSOCKET_FRESHNESS, 5.0)  # clear
        assert len(m.alert_history()) == 1

    def test_multiple_slis_independent(self) -> None:
        m = _monitor()
        m.record(SLIName.WEBSOCKET_FRESHNESS, 60.0)
        m.record(SLIName.ORDER_LATENCY, 1000.0)
        assert len(m.active_alerts()) == 2

    def test_unknown_sli_returns_none(self) -> None:
        # A monitor with no targets for an SLI should return None
        m = SLOMonitor(targets={})
        result = m.record(SLIName.WEBSOCKET_FRESHNESS, 999.0)
        assert result is None

    def test_alert_has_runbook_url(self) -> None:
        m = _monitor()
        alert = m.record(SLIName.WEBSOCKET_FRESHNESS, 200.0)
        assert alert is not None
        assert alert.runbook_url != ""

    def test_filter_active_by_sli(self) -> None:
        m = _monitor()
        m.record(SLIName.WEBSOCKET_FRESHNESS, 60.0)
        m.record(SLIName.ORDER_LATENCY, 1000.0)
        ws_alerts = m.active_alerts(SLIName.WEBSOCKET_FRESHNESS)
        assert len(ws_alerts) == 1
        assert ws_alerts[0].sli == SLIName.WEBSOCKET_FRESHNESS


class TestAlertRoutingPolicy:
    def test_warning_includes_telegram(self) -> None:
        policy = AlertRoutingPolicy()
        channels = policy.channels_for(AlertSeverity.WARNING)
        assert "telegram" in channels

    def test_critical_includes_telegram(self) -> None:
        policy = AlertRoutingPolicy()
        channels = policy.channels_for(AlertSeverity.CRITICAL)
        assert "telegram" in channels

    def test_page_includes_pagerduty(self) -> None:
        policy = AlertRoutingPolicy()
        channels = policy.channels_for(AlertSeverity.PAGE)
        assert "pagerduty" in channels

    def test_info_log_only(self) -> None:
        policy = AlertRoutingPolicy()
        channels = policy.channels_for(AlertSeverity.INFO)
        assert channels == ["log"]


class TestSLOMonitorSingleton:
    def test_singleton_returns_same_instance(self) -> None:
        assert get_slo_monitor() is get_slo_monitor()
