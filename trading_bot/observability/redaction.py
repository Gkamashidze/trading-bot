"""Redact credentials at the final logging boundary, including third-party logs."""

from __future__ import annotations

import os
import re
from collections.abc import MutableMapping
from typing import Any

_SECRET_FIELDS = frozenset(
    {
        "api_key",
        "api_secret",
        "secret_key",
        "secret",
        "password",
        "passwd",
        "bot_token",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "set_cookie",
        "database_url",
        "fred_api_key",
    }
)
_SECRET_ENV = (
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "TELEGRAM_BOT_TOKEN",
    "FRED_API_KEY",
    "SECRET_KEY",
    "DASHBOARD_API_KEY",
    "DATABASE_URL",
    "PGPASSWORD",
)
_TELEGRAM_TOKEN = re.compile(r"(?<![0-9])\d{6,}:[A-Za-z0-9_-]{20,}")
_URL_PASSWORD = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]+@", re.I)
_AUTHORIZATION = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9+/_.=-]+", re.I)
_SECRET_PARAMETER = re.compile(
    r"(?i)(\b(?:api[_-]?key|api[_-]?secret|secret[_-]?key|password|"
    r"bot[_-]?token|access[_-]?token|refresh[_-]?token|signature)[\"']?\s*[=:]\s*[\"']?)"
    r"([^\s&,;\"']+)"
)


def redact_text(value: str) -> str:
    """Remove credential patterns and configured secret values from arbitrary text."""
    for name in _SECRET_ENV:
        secret = os.environ.get(name, "")
        if len(secret) >= 8:
            value = value.replace(secret, "[REDACTED]")
    value = _TELEGRAM_TOKEN.sub("[REDACTED]", value)
    value = _URL_PASSWORD.sub(r"\1[REDACTED]@", value)
    value = _AUTHORIZATION.sub(r"\1 [REDACTED]", value)
    return _SECRET_PARAMETER.sub(r"\1[REDACTED]", value)


def redact_secrets(value: Any) -> Any:
    """Recursively scrub structured fields, strings, exceptions and nested containers."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if str(key).lower().replace("-", "_") in _SECRET_FIELDS
            else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, BaseException):
        return redact_text(str(value))
    if isinstance(value, bytes):
        return redact_text(value.decode("utf-8", errors="replace"))
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value))


def redact_log_event(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> dict[str, Any]:
    """Structlog processor applied after exception formatting and before rendering."""
    result: dict[str, Any] = redact_secrets(event_dict)
    return result
