"""Event schema upcaster registry.

When an event's schema_version changes, register an upcaster that mutates
the raw dict from the old version to the new version. `upcast()` applies all
relevant upcasters in version order so stored events remain replayable forever.

Design: upcasters are applied sequentially (1.0→1.1→2.0) rather than all
at once so each upcaster only needs to know the single step it handles.

Usage:
    # Register a migration (e.g. market.ohlcv 1.0 → 2.0):
    @register_upcaster("market.ohlcv", from_version="1.0")
    def _upcast_ohlcv_v1(raw: dict) -> None:
        raw["schema_version"] = "2.0"
        raw.setdefault("trade_count", None)  # new optional field

    # Deserialize from storage:
    raw = json.loads(db_row["payload"])
    upcasted = upcast(raw)
    event = EVENT_REGISTRY[upcasted["event_type"]](**upcasted)
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

# Key: (event_type, from_version) → callable that mutates the dict and bumps schema_version
_UPCASTERS: dict[tuple[str, str], Callable[[dict[str, Any]], None]] = {}

# Sorted list of from-versions per event_type — defines upcasting order
_VERSION_ORDER: dict[str, list[str]] = {}


def register_upcaster(
    event_type: str, from_version: str
) -> Callable[[Callable[[dict[str, Any]], None]], Callable[[dict[str, Any]], None]]:
    """Decorator that registers a schema migration for a specific event type and version."""

    def decorator(
        fn: Callable[[dict[str, Any]], None],
    ) -> Callable[[dict[str, Any]], None]:
        _UPCASTERS[(event_type, from_version)] = fn
        versions = _VERSION_ORDER.setdefault(event_type, [])
        if from_version not in versions:
            versions.append(from_version)
            _VERSION_ORDER[event_type] = sorted(versions)
        log.debug("upcaster_registered", event_type=event_type, from_version=from_version)
        return fn

    return decorator


def upcast(raw: dict[str, Any]) -> dict[str, Any]:
    """Bring a raw event dict to the latest schema version.

    Applies upcasters sequentially in version order. The input dict is not
    mutated — a shallow copy is made and returned.
    Returns the dict unchanged if no upcasters are registered for its type.
    """
    result = dict(raw)
    event_type = result.get("event_type", "")
    versions = _VERSION_ORDER.get(event_type, [])

    for version in versions:
        if result.get("schema_version") != version:
            continue
        upcaster = _UPCASTERS.get((event_type, version))
        if upcaster is None:
            continue
        upcaster(result)
        log.debug(
            "event_upcasted",
            event_type=event_type,
            from_version=version,
            to_version=result.get("schema_version"),
        )

    return result


def get_registered_upcasters() -> dict[tuple[str, str], Callable[[dict[str, Any]], None]]:
    """Return a copy of the upcaster registry (for inspection and testing)."""
    return dict(_UPCASTERS)
