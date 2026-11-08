"""Credentials must not reach either structured or third-party log output."""

from __future__ import annotations

import logging

import pytest

from trading_bot.observability.logging import configure_logging, get_logger
from trading_bot.observability.redaction import redact_secrets, redact_text

TOKEN = "123456789:FAKE_TOKEN_FOR_TESTS_ONLY_abcdefghijklmno"


def test_nested_fields_and_embedded_credentials_are_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "test-configured-secret-for-redaction"
    monkeypatch.setenv("FRED_API_KEY", secret)
    data = {"api-key": "private", "nested": [{"event": f"{TOKEN} {secret}"}]}
    clean = str(redact_secrets(data))
    assert TOKEN not in clean and secret not in clean and "private" not in clean
    assert data["api-key"] == "private"  # redaction must not mutate caller state


@pytest.mark.parametrize("fmt", ["json", "console"])
def test_stdlib_and_exception_logs_are_scrubbed(
    fmt: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    configure_logging(fmt=fmt)
    logging.getLogger("redaction-test").warning(
        "HTTP GET https://api.telegram.org/bot%s/getMe", TOKEN
    )
    try:
        raise ValueError(f"request failed: {TOKEN}")
    except ValueError:
        get_logger("redaction-exception").exception("test failure", token=TOKEN)
    output = capsys.readouterr().out
    assert TOKEN not in output
    assert "[REDACTED]" in output
    assert "ValueError" in output


def test_url_authorization_and_query_credentials() -> None:
    result = redact_text("postgresql://operator:private@db/x Bearer abc123 api_key=abcdef&ok=true")
    assert "private" not in result and "abc123" not in result and "abcdef" not in result
    assert "ok=true" in result


def test_settings_repr_and_snapshot_hide_nested_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    from trading_bot.config.settings import Settings

    monkeypatch.setenv("FRED_API_KEY", "fred-secret-value")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    settings = Settings(environment="development")
    assert TOKEN not in repr(settings)
    assert "fred-secret-value" not in repr(settings)
    assert "fred-secret-value" not in str(settings.snapshot())
