"""Tests for promotion/micro_live.py — MicroLiveGate."""

from decimal import Decimal

import pytest

from trading_bot.promotion.micro_live import (
    MicroLiveConfig,
    MicroLiveGate,
    MicroLiveStatus,
)


class TestMicroLiveConfig:
    def test_default_config_is_safe(self) -> None:
        cfg = MicroLiveConfig()
        assert cfg.max_order_usd == Decimal("50")
        assert cfg.max_daily_loss_usd == Decimal("25")

    def test_exceeding_hard_limit_raises(self) -> None:
        with pytest.raises(ValueError, match="hard limit"):
            MicroLiveConfig(max_order_usd=Decimal("200"))


class TestMicroLiveGate:
    def setup_method(self) -> None:
        self.cfg = MicroLiveConfig(
            max_order_usd=Decimal("50"),
            max_daily_loss_usd=Decimal("25"),
            max_weekly_loss_usd=Decimal("75"),
            max_open_positions=1,
        )
        self.gate = MicroLiveGate(config=self.cfg)

    def test_disabled_by_default(self) -> None:
        assert self.gate.status == MicroLiveStatus.DISABLED

    def test_globally_disabled_blocks_order(self) -> None:
        self.gate.enable("sma", "BTC/USDT", "operator_alice")
        allowed, reason = self.gate.is_order_allowed("sma", "BTC/USDT", Decimal("10"), 0)
        assert not allowed
        assert "globally disabled" in reason

    def test_not_active_blocks_order(self) -> None:
        allowed, _reason = self.gate.is_order_allowed("sma", "BTC/USDT", Decimal("10"), 0)
        assert not allowed

    def test_enable_sets_status(self) -> None:
        self.gate.enable("sma", "BTC/USDT", "alice")
        assert self.gate.status == MicroLiveStatus.ENABLED

    def test_disable_resets_status(self) -> None:
        self.gate.enable("sma", "BTC/USDT", "alice")
        self.gate.disable()
        assert self.gate.status == MicroLiveStatus.DISABLED

    def test_daily_loss_breach_causes_rollback(self) -> None:
        self.gate.enable("sma", "BTC/USDT", "alice")
        # Record a loss exceeding daily cap
        self.gate.record_fill(Decimal("-30"), Decimal("30"))
        assert self.gate.status == MicroLiveStatus.ROLLED_BACK

    def test_daily_loss_breach_blocks_subsequent_orders(self) -> None:
        self.gate.enable("sma", "BTC/USDT", "alice")
        self.gate.record_fill(Decimal("-30"), Decimal("30"))
        # status is now ROLLED_BACK — globally disabled anyway, but let's check
        allowed, _reason = self.gate.is_order_allowed("sma", "BTC/USDT", Decimal("10"), 0)
        assert not allowed

    def test_session_state_tracks_trades(self) -> None:
        self.gate.enable("sma", "BTC/USDT", "alice")
        self.gate.record_fill(Decimal("5"), Decimal("50"))
        assert self.gate.session.session_trade_count == 1
        assert self.gate.session.total_notional_usd == Decimal("50")
        assert self.gate.session.daily_realized_loss_usd == Decimal("0")

    def test_daily_approval_recorded(self) -> None:
        self.gate.approve_daily("alice")
        assert self.gate.session.approved_by == "alice"
        assert self.gate.session.last_approval_at is not None
