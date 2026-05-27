"""Tests for trading_bot/exchange/rate_limit.py — circuit breaker + rate limit awareness."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from trading_bot.exchange import rate_limit


@pytest.fixture(autouse=True)
def reset_circuits() -> None:
    """Wipe the module-level circuits between tests."""
    rate_limit.configure_state_store(None)
    rate_limit._circuits.clear()
    rate_limit._request_locks.clear()


class TestParseBanTimestamp:
    def test_extracts_timestamp_from_binance_error(self) -> None:
        msg = (
            'binance 418 Unknown {"code":-1003,"msg":"Way too many requests; '
            'IP(1.2.3.4) banned until 1779808947147. Please use the websocket"}'
        )
        assert rate_limit.parse_ban_timestamp_ms(msg) == 1779808947147

    def test_returns_none_when_no_ban_in_message(self) -> None:
        assert rate_limit.parse_ban_timestamp_ms("connection reset by peer") is None

    def test_handles_case_insensitivity(self) -> None:
        assert rate_limit.parse_ban_timestamp_ms("Banned Until 1234567890") == 1234567890


class TestCircuitBreaker:
    def test_closed_initially(self) -> None:
        assert rate_limit.check_circuit("binance") == 0

    def test_trip_opens_circuit(self) -> None:
        # Trip the circuit for ~10 minutes in the future
        future_ms = int(time.time() * 1000) + 600_000
        rate_limit.trip_circuit("binance", future_ms)

        remaining = rate_limit.check_circuit("binance")
        assert 590 < remaining <= 600  # ~10 minutes

    def test_circuit_resets_when_ban_expires(self) -> None:
        # Trip with a past timestamp — should immediately reset
        past_ms = int(time.time() * 1000) - 1000
        rate_limit.trip_circuit("binance", past_ms)

        assert rate_limit.check_circuit("binance") == 0

    def test_isolated_per_exchange(self) -> None:
        future_ms = int(time.time() * 1000) + 60_000
        rate_limit.trip_circuit("binance", future_ms)

        assert rate_limit.check_circuit("binance") > 0
        assert rate_limit.check_circuit("kraken") == 0

    def test_persisted_ban_survives_process_restart(self, tmp_path: Path) -> None:
        path = tmp_path / "exchange_circuit_state.json"
        future_ms = int(time.time() * 1000) + 600_000
        rate_limit.configure_state_store(path)
        rate_limit.trip_circuit("binance", future_ms)

        rate_limit._circuits.clear()
        rate_limit.configure_state_store(path)

        assert rate_limit.check_circuit("binance") > 0


class TestBanAlertDedup:
    def test_first_alert_passes(self) -> None:
        assert rate_limit.should_alert_ban("binance") is True

    def test_second_alert_within_window_blocked(self) -> None:
        rate_limit.should_alert_ban("binance")
        assert rate_limit.should_alert_ban("binance") is False

    def test_alert_passes_after_window_expires(self) -> None:
        rate_limit.should_alert_ban("binance")
        # Set last_ban_alert_at far enough in the past
        rate_limit._circuits["binance"].last_ban_alert_at = time.time() - 7200
        assert rate_limit.should_alert_ban("binance") is True


class TestRateLimitAwareness:
    def test_no_throttle_when_unused(self) -> None:
        assert rate_limit.should_throttle("binance") is False

    def test_no_throttle_under_soft_limit(self) -> None:
        # 60% of 6000 = 3600 — under 80% threshold
        rate_limit.record_weight("binance", 3600)
        assert rate_limit.should_throttle("binance") is False

    def test_throttle_above_soft_limit(self) -> None:
        # 85% of 6000 = 5100 — over 80% threshold
        rate_limit.record_weight("binance", 5100)
        assert rate_limit.should_throttle("binance") is True

    def test_retry_after_cooldown_is_persisted(self, tmp_path: Path) -> None:
        path = tmp_path / "exchange_circuit_state.json"
        rate_limit.configure_state_store(path)
        rate_limit.mark_rate_limited("binance", 120)

        rate_limit._circuits.clear()
        rate_limit.configure_state_store(path)

        assert rate_limit.check_rate_limit_cooldown("binance") >= 118


class TestEdgeTriggeredWeightAlerts:
    def test_no_alert_under_warning_threshold(self) -> None:
        # 60% — below 70% warning threshold
        rate_limit.record_weight("binance", 3600)
        assert rate_limit.get_circuit("binance").last_weight_alert_level == ""

    def test_warning_alert_at_70_pct(self) -> None:
        # 75% — above 70% warning threshold
        rate_limit.record_weight("binance", 4500)
        assert rate_limit.get_circuit("binance").last_weight_alert_level == "warning"

    def test_critical_alert_at_90_pct(self) -> None:
        # 91% — above 90% critical threshold
        rate_limit.record_weight("binance", 5460)
        assert rate_limit.get_circuit("binance").last_weight_alert_level == "critical"

    def test_warning_then_critical_re_alerts(self) -> None:
        # Start at warning level
        rate_limit.record_weight("binance", 4500)
        assert rate_limit.get_circuit("binance").last_weight_alert_level == "warning"
        # Force timestamp far in the past so the 5min dedup doesn't block us
        rate_limit.get_circuit("binance").last_weight_alert_at = 0.0
        # Escalate to critical — should re-alert (different level)
        rate_limit.record_weight("binance", 5460)
        assert rate_limit.get_circuit("binance").last_weight_alert_level == "critical"

    def test_alert_level_resets_when_back_under_warning(self) -> None:
        rate_limit.record_weight("binance", 5460)  # critical
        assert rate_limit.get_circuit("binance").last_weight_alert_level == "critical"
        rate_limit.record_weight("binance", 1000)  # back to safe
        assert rate_limit.get_circuit("binance").last_weight_alert_level == ""

    def test_repeated_warning_does_not_re_alert(self) -> None:
        # First warning fires
        rate_limit.record_weight("binance", 4500)
        # Reset the timestamp tracker but keep the level — repeated warning shouldn't re-alert
        c = rate_limit.get_circuit("binance")
        first_alert_at = c.last_weight_alert_at
        c.last_weight_alert_at = 0.0  # force "long ago" so dedup wouldn't block
        rate_limit.record_weight("binance", 4600)  # still warning
        # last_weight_alert_at should be unchanged (no new alert fired) because
        # the LEVEL didn't change from "warning" to "critical"
        assert c.last_weight_alert_at == 0.0
        assert first_alert_at > 0  # sanity check on the first alert
