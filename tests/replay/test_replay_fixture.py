"""Replay regression test — verifies that the event stream fixture loads correctly.

A full replay engine is implemented in Stage 4. For now, this test validates:
1. Fixture file parses correctly (JSON schema)
2. Events deserialize into the correct event types
3. Expected outcomes match the event stream content

This establishes the replay fixture format that Stage 4 will build upon.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.mark.replay
def test_example_fixture_loads() -> None:
    """Fixture file must be valid JSON with required top-level keys."""
    fixture_path = FIXTURE_DIR / "example_event_stream.json"
    assert fixture_path.exists(), f"Fixture file missing: {fixture_path}"

    data = json.loads(fixture_path.read_text())

    assert "schema_version" in data
    assert "events" in data
    assert "expected_outcomes" in data
    assert "config_snapshot" in data


@pytest.mark.replay
def test_fixture_events_have_required_fields() -> None:
    """Every event in the fixture must have event_id, event_type, occurred_at."""
    fixture_path = FIXTURE_DIR / "example_event_stream.json"
    data = json.loads(fixture_path.read_text())

    for i, event in enumerate(data["events"]):
        assert "event_id" in event, f"Event {i} missing event_id"
        assert "event_type" in event, f"Event {i} missing event_type"
        assert "occurred_at" in event, f"Event {i} missing occurred_at"
        assert "correlation_id" in event, f"Event {i} missing correlation_id"


@pytest.mark.replay
def test_fixture_event_types_are_registered() -> None:
    """All event types in the fixture must be in the EVENT_REGISTRY."""
    from trading_bot.core.events import EVENT_REGISTRY

    fixture_path = FIXTURE_DIR / "example_event_stream.json"
    data = json.loads(fixture_path.read_text())

    for event in data["events"]:
        event_type = event["event_type"]
        assert event_type in EVENT_REGISTRY, (
            f"Event type '{event_type}' not found in EVENT_REGISTRY. "
            "Register it in trading_bot/core/events.py"
        )


@pytest.mark.replay
def test_fixture_expected_outcomes_match_events() -> None:
    """The number of signal events matches expected_outcomes.signals_generated."""
    fixture_path = FIXTURE_DIR / "example_event_stream.json"
    data = json.loads(fixture_path.read_text())

    signal_events = [e for e in data["events"] if e["event_type"] == "strategy.signal"]
    expected_signals = data["expected_outcomes"]["signals_generated"]
    assert len(signal_events) == expected_signals

    order_events = [e for e in data["events"] if e["event_type"] == "execution.order"]
    expected_orders = data["expected_outcomes"]["orders_submitted"]
    assert len(order_events) == expected_orders
