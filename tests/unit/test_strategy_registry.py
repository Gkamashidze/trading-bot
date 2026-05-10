"""Unit tests for the Strategy Governance Registry (Feature #5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from trading_bot.promotion.pipeline import (
    PromotionTier,
    StrategyMetrics,
    StrategyPromotion,
)
from trading_bot.strategies.registry import (
    ApprovalRecord,
    RegistryError,
    StrategyRegistry,
    StrategyRegistryEntry,
    hash_params,
)


def _entry(strategy_id: str = "s1", version: str = "1.0.0") -> StrategyRegistryEntry:
    return StrategyRegistryEntry(strategy_id=strategy_id, version=version, owner="test")


def _approved_entry(strategy_id: str = "s1") -> StrategyRegistryEntry:
    entry = _entry(strategy_id)
    entry.add_approval(
        ApprovalRecord(
            approver="alice",
            decision="approved",
            recorded_at=datetime.now(UTC),
        )
    )
    return entry


class TestStrategyRegistryEntry:
    def test_new_entry_is_pending(self) -> None:
        entry = _entry()
        assert entry.promotion_status == "pending"
        assert not entry.is_approved()
        assert not entry.is_valid()

    def test_approve_sets_approved(self) -> None:
        entry = _approved_entry()
        assert entry.is_approved()
        assert entry.is_valid()

    def test_reject_sets_rejected(self) -> None:
        entry = _entry()
        entry.add_approval(
            ApprovalRecord(
                approver="bob",
                decision="rejected",
                recorded_at=datetime.now(UTC),
                note="poor backtest",
            )
        )
        assert not entry.is_approved()
        assert not entry.is_valid()

    def test_expired_entry_not_valid(self) -> None:
        entry = _approved_entry()
        # Manually set expiry in the past
        past = datetime.now(UTC) - timedelta(seconds=1)
        # dataclass is mutable
        entry.expiry_date = past
        assert entry.is_expired()
        assert not entry.is_valid()

    def test_not_expired_when_no_expiry_date(self) -> None:
        entry = _approved_entry()
        assert not entry.is_expired()

    def test_approval_history_appended(self) -> None:
        entry = _entry()
        r1 = ApprovalRecord(approver="a", decision="rejected", recorded_at=datetime.now(UTC))
        r2 = ApprovalRecord(approver="b", decision="approved", recorded_at=datetime.now(UTC))
        entry.add_approval(r1)
        entry.add_approval(r2)
        assert len(entry.approval_history) == 2
        assert entry.promotion_status == "approved"

    def test_expire_sets_status(self) -> None:
        entry = _approved_entry()
        entry.expire()
        assert entry.promotion_status == "expired"
        assert not entry.is_valid()


class TestStrategyRegistry:
    def setup_method(self) -> None:
        self.registry = StrategyRegistry()

    def test_register_and_get(self) -> None:
        entry = _entry("s1")
        self.registry.register(entry)
        assert self.registry.get("s1") is entry

    def test_get_missing_returns_none(self) -> None:
        assert self.registry.get("nonexistent") is None

    def test_approve(self) -> None:
        self.registry.register(_entry("s1"))
        updated = self.registry.approve("s1", approver="alice", note="looks good")
        assert updated.is_approved()
        assert updated.approval_history[-1].approver == "alice"

    def test_approve_nonexistent_raises(self) -> None:
        with pytest.raises(KeyError):
            self.registry.approve("ghost", approver="alice")

    def test_reject(self) -> None:
        self.registry.register(_entry("s1"))
        updated = self.registry.reject("s1", approver="bob", note="too risky")
        assert not updated.is_approved()

    def test_expire(self) -> None:
        self.registry.register(_approved_entry("s1"))
        updated = self.registry.expire("s1")
        assert updated.promotion_status == "expired"

    def test_require_valid_raises_if_missing(self) -> None:
        with pytest.raises(RegistryError, match="not in governance registry"):
            self.registry.require_valid_entry("unknown")

    def test_require_valid_raises_if_pending(self) -> None:
        self.registry.register(_entry("s1"))
        with pytest.raises(RegistryError, match="not approved"):
            self.registry.require_valid_entry("s1")

    def test_require_valid_raises_if_expired(self) -> None:
        entry = _approved_entry("s1")
        entry.expiry_date = datetime.now(UTC) - timedelta(seconds=1)
        self.registry.register(entry)
        with pytest.raises(RegistryError, match="expired"):
            self.registry.require_valid_entry("s1")

    def test_require_valid_passes_for_approved(self) -> None:
        self.registry.register(_approved_entry("s1"))
        self.registry.require_valid_entry("s1")  # must not raise

    def test_all_entries(self) -> None:
        self.registry.register(_entry("s1"))
        self.registry.register(_entry("s2"))
        assert len(self.registry.all_entries()) == 2

    def test_register_replaces_existing(self) -> None:
        self.registry.register(_entry("s1", "1.0.0"))
        self.registry.register(_entry("s1", "2.0.0"))
        assert self.registry.get("s1").version == "2.0.0"  # type: ignore[union-attr]


class TestHashParams:
    def test_same_params_same_hash(self) -> None:
        p = {"fast": 3, "slow": 10}
        assert hash_params(p) == hash_params(p)

    def test_order_independent(self) -> None:
        p1 = {"a": 1, "b": 2}
        p2 = {"b": 2, "a": 1}
        assert hash_params(p1) == hash_params(p2)

    def test_different_params_different_hash(self) -> None:
        assert hash_params({"a": 1}) != hash_params({"a": 2})

    def test_hash_is_hex_string(self) -> None:
        h = hash_params({"x": 42})
        assert len(h) == 64
        int(h, 16)  # must be valid hex


class TestPromotionWithRegistry:
    """Promotion pipeline must refuse to advance without a valid registry entry."""

    def _good_metrics(self) -> StrategyMetrics:
        return StrategyMetrics(
            days_running=8,
            sharpe_ratio=0.9,
            max_drawdown_pct=0.10,
            win_rate=0.55,
            total_trades=15,
        )

    def test_advance_blocked_without_registry_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from trading_bot.strategies.registry import StrategyRegistry

        empty_registry = StrategyRegistry()
        monkeypatch.setattr(
            "trading_bot.strategies.registry._registry",
            empty_registry,
        )

        promo = StrategyPromotion(strategy_id="no_entry")
        with pytest.raises(RegistryError):
            promo.advance(self._good_metrics(), require_registry=True)

    def test_advance_blocked_with_unapproved_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from trading_bot.strategies.registry import StrategyRegistry

        reg = StrategyRegistry()
        reg.register(_entry("pending_strat"))  # not approved
        monkeypatch.setattr("trading_bot.strategies.registry._registry", reg)

        promo = StrategyPromotion(strategy_id="pending_strat")
        with pytest.raises(RegistryError, match="not approved"):
            promo.advance(self._good_metrics(), require_registry=True)

    def test_advance_succeeds_with_valid_registry_entry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from trading_bot.strategies.registry import StrategyRegistry

        reg = StrategyRegistry()
        reg.register(_approved_entry("good_strat"))
        monkeypatch.setattr("trading_bot.strategies.registry._registry", reg)

        promo = StrategyPromotion(strategy_id="good_strat", current_tier=PromotionTier.SHADOW)
        new_tier = promo.advance(self._good_metrics(), require_registry=True)
        assert new_tier == PromotionTier.PAPER

    def test_advance_skips_registry_when_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from trading_bot.strategies.registry import StrategyRegistry

        empty_registry = StrategyRegistry()
        monkeypatch.setattr("trading_bot.strategies.registry._registry", empty_registry)

        promo = StrategyPromotion(strategy_id="no_entry")
        # require_registry=False should bypass the check
        result = promo.advance(self._good_metrics(), require_registry=False)
        assert result == PromotionTier.PAPER
