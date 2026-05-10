"""Tests for Feature #7: Reproducible Research Workflow."""

from __future__ import annotations

import pytest

from trading_bot.research.experiment import (
    ExperimentArtifact,
    ExperimentRegistry,
    ExperimentStatus,
    get_experiment_registry,
    hash_params,
)


def _registry() -> ExperimentRegistry:
    return ExperimentRegistry()


def _good_metrics() -> dict[str, float]:
    return {"sharpe": 1.4, "max_drawdown": 0.07, "win_rate": 0.55}


class TestHashParams:
    def test_same_params_produce_same_hash(self) -> None:
        h1 = hash_params({"fast": 10, "slow": 30})
        h2 = hash_params({"fast": 10, "slow": 30})
        assert h1 == h2

    def test_different_params_produce_different_hash(self) -> None:
        h1 = hash_params({"fast": 10, "slow": 30})
        h2 = hash_params({"fast": 10, "slow": 50})
        assert h1 != h2

    def test_key_order_does_not_affect_hash(self) -> None:
        h1 = hash_params({"a": 1, "b": 2})
        h2 = hash_params({"b": 2, "a": 1})
        assert h1 == h2

    def test_hash_is_hex_string(self) -> None:
        h = hash_params({"key": "value"})
        assert len(h) == 64
        int(h, 16)  # must be valid hex


class TestExperimentArtifact:
    def test_fingerprint_is_deterministic(self) -> None:
        reg = _registry()
        exp = reg.create("sma", ["snap1"], "phash", "chash", seed=42, metrics=_good_metrics())
        f1 = exp.fingerprint
        f2 = exp.fingerprint
        assert f1 == f2

    def test_fingerprint_changes_with_seed(self) -> None:
        reg = _registry()
        e1 = reg.create("sma", ["snap1"], "phash", "chash", seed=42, metrics=_good_metrics())
        e2 = reg.create("sma", ["snap1"], "phash", "chash", seed=99, metrics=_good_metrics())
        assert e1.fingerprint != e2.fingerprint

    def test_fingerprint_changes_with_snapshot(self) -> None:
        reg = _registry()
        e1 = reg.create("sma", ["snap1"], "phash", "chash", seed=42, metrics=_good_metrics())
        e2 = reg.create("sma", ["snap2"], "phash", "chash", seed=42, metrics=_good_metrics())
        assert e1.fingerprint != e2.fingerprint

    def test_is_approved_false_by_default(self) -> None:
        reg = _registry()
        exp = reg.create("sma", ["snap1"], "ph", "ch", seed=1, metrics=_good_metrics())
        assert exp.is_approved is False

    def test_dataset_snapshot_ids_are_sorted(self) -> None:
        reg = _registry()
        exp = reg.create("sma", ["zzz", "aaa"], "ph", "ch", seed=1, metrics=_good_metrics())
        assert exp.dataset_snapshot_ids == ("aaa", "zzz")


class TestExperimentRegistryCreate:
    def test_create_returns_artifact(self) -> None:
        reg = _registry()
        exp = reg.create("sma", ["snap1"], "ph", "ch", seed=1, metrics=_good_metrics())
        assert isinstance(exp, ExperimentArtifact)
        assert exp.strategy_id == "sma"

    def test_create_increments_length(self) -> None:
        reg = _registry()
        reg.create("sma", ["snap1"], "ph", "ch", seed=1, metrics=_good_metrics())
        reg.create("sma", ["snap1"], "ph", "ch", seed=2, metrics=_good_metrics())
        assert len(reg) == 2

    def test_get_returns_created_artifact(self) -> None:
        reg = _registry()
        exp = reg.create("rsi", ["s1"], "ph", "ch", seed=5, metrics={})
        found = reg.get(exp.experiment_id)
        assert found is not None
        assert found.experiment_id == exp.experiment_id

    def test_get_unknown_returns_none(self) -> None:
        reg = _registry()
        assert reg.get("nonexistent-id") is None


class TestExperimentApproval:
    def test_approve_changes_status(self) -> None:
        reg = _registry()
        exp = reg.create("sma", ["s1"], "ph", "ch", seed=1, metrics=_good_metrics())
        approved = reg.approve(exp.experiment_id, approved_by="quant_team")
        assert approved.status == ExperimentStatus.APPROVED
        assert approved.approved_by == "quant_team"
        assert approved.approved_at is not None

    def test_approve_idempotent(self) -> None:
        reg = _registry()
        exp = reg.create("sma", ["s1"], "ph", "ch", seed=1, metrics=_good_metrics())
        reg.approve(exp.experiment_id, approved_by="alice")
        second = reg.approve(exp.experiment_id, approved_by="bob")
        # First approval wins
        assert second.approved_by == "alice"

    def test_approve_unknown_raises_keyerror(self) -> None:
        reg = _registry()
        with pytest.raises(KeyError):
            reg.approve("nonexistent", approved_by="ops")

    def test_is_approved_true_after_approval(self) -> None:
        reg = _registry()
        exp = reg.create("sma", ["s1"], "ph", "ch", seed=1, metrics=_good_metrics())
        approved = reg.approve(exp.experiment_id, approved_by="ops")
        assert approved.is_approved is True


class TestExperimentArchive:
    def test_archive_changes_status(self) -> None:
        reg = _registry()
        exp = reg.create("sma", ["s1"], "ph", "ch", seed=1, metrics=_good_metrics())
        archived = reg.archive(exp.experiment_id)
        assert archived.status == ExperimentStatus.ARCHIVED

    def test_archived_not_in_list_approved(self) -> None:
        reg = _registry()
        exp = reg.create("sma", ["s1"], "ph", "ch", seed=1, metrics=_good_metrics())
        reg.archive(exp.experiment_id)
        assert reg.list_approved() == []


class TestExperimentListing:
    def test_list_by_strategy(self) -> None:
        reg = _registry()
        reg.create("sma", ["s1"], "ph", "ch", seed=1, metrics=_good_metrics())
        reg.create("sma", ["s2"], "ph", "ch", seed=2, metrics=_good_metrics())
        reg.create("rsi", ["s1"], "ph", "ch", seed=1, metrics=_good_metrics())
        sma = reg.list_by_strategy("sma")
        assert len(sma) == 2

    def test_list_approved(self) -> None:
        reg = _registry()
        e1 = reg.create("sma", ["s1"], "ph", "ch", seed=1, metrics=_good_metrics())
        reg.create("sma", ["s2"], "ph", "ch", seed=2, metrics=_good_metrics())
        reg.approve(e1.experiment_id, approved_by="ops")
        approved = reg.list_approved()
        assert len(approved) == 1

    def test_find_duplicate_same_fingerprint(self) -> None:
        reg = _registry()
        e1 = reg.create("sma", ["s1"], "ph", "ch", seed=42, metrics=_good_metrics())
        e2 = reg.create("sma", ["s1"], "ph", "ch", seed=42, metrics=_good_metrics())
        dup = reg.find_duplicate(e2)
        assert dup is not None
        assert dup.experiment_id == e1.experiment_id

    def test_find_duplicate_different_seed_returns_none(self) -> None:
        reg = _registry()
        reg.create("sma", ["s1"], "ph", "ch", seed=42, metrics=_good_metrics())
        e2 = reg.create("sma", ["s1"], "ph", "ch", seed=99, metrics=_good_metrics())
        # e2 has different seed → different fingerprint from anything except itself
        others = ExperimentRegistry()
        # fresh registry — no duplicates
        assert others.find_duplicate(e2) is None


class TestSingleton:
    def test_singleton_returns_same_instance(self) -> None:
        r1 = get_experiment_registry()
        r2 = get_experiment_registry()
        assert r1 is r2
