"""Tests for the event schema upcaster registry."""

from __future__ import annotations

from trading_bot.core.event_migration import (
    get_registered_upcasters,
    register_upcaster,
    upcast,
)

# Use unique event type names per test to avoid cross-test registry pollution


class TestRegisterUpcaster:
    def test_registers_fn_in_registry(self) -> None:
        @register_upcaster("test.register_a", from_version="0.9")
        def _(raw: dict) -> None:
            raw["schema_version"] = "1.0"

        assert ("test.register_a", "0.9") in get_registered_upcasters()

    def test_decorator_returns_original_fn(self) -> None:
        def original(raw: dict) -> None:
            pass

        result = register_upcaster("test.decorator_b", from_version="1.0")(original)
        assert result is original


class TestUpcast:
    def test_noop_for_current_version_with_no_upcaster(self) -> None:
        raw = {"event_type": "market.ohlcv", "schema_version": "1.0", "extra": 42}
        result = upcast(raw)
        assert result["schema_version"] == "1.0"
        assert result["extra"] == 42

    def test_applies_registered_upcaster(self) -> None:
        @register_upcaster("test.apply_c", from_version="1.0")
        def _(raw: dict) -> None:
            raw["schema_version"] = "2.0"
            raw["new_field"] = "added"

        raw = {"event_type": "test.apply_c", "schema_version": "1.0"}
        result = upcast(raw)
        assert result["schema_version"] == "2.0"
        assert result["new_field"] == "added"

    def test_does_not_mutate_input_dict(self) -> None:
        raw = {"event_type": "market.ohlcv", "schema_version": "1.0"}
        original_id = id(raw)
        result = upcast(raw)
        assert id(result) != original_id
        assert raw == {"event_type": "market.ohlcv", "schema_version": "1.0"}

    def test_unknown_event_type_passes_through_unchanged(self) -> None:
        raw = {"event_type": "completely.unknown", "schema_version": "99.0"}
        result = upcast(raw)
        assert result == raw

    def test_wrong_version_does_not_apply_upcaster(self) -> None:
        applied = []

        @register_upcaster("test.version_gate_d", from_version="1.0")
        def _(raw: dict) -> None:
            applied.append(True)
            raw["schema_version"] = "2.0"

        raw = {"event_type": "test.version_gate_d", "schema_version": "2.0"}
        upcast(raw)
        assert applied == []  # upcaster not triggered for already-current version

    def test_sequential_upcasting_multiple_versions(self) -> None:
        @register_upcaster("test.sequential_e", from_version="1.0")
        def _v1(raw: dict) -> None:
            raw["schema_version"] = "1.1"
            raw["step1"] = True

        @register_upcaster("test.sequential_e", from_version="1.1")
        def _v11(raw: dict) -> None:
            raw["schema_version"] = "2.0"
            raw["step2"] = True

        raw = {"event_type": "test.sequential_e", "schema_version": "1.0"}
        result = upcast(raw)
        assert result["schema_version"] == "2.0"
        assert result["step1"] is True
        assert result["step2"] is True
