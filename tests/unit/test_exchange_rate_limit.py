"""Tests for trading_bot/exchange/rate_limit.py — circuit breaker + rate limit awareness."""

from __future__ import annotations

import time

import pytest

from trading_bot.exchange import rate_limit


@pytest.fixture(autouse=True)
def reset_circuits() -> None:
    """Wipe the module-level circuits between tests."""
    rate_limit._circuits.clear()


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
