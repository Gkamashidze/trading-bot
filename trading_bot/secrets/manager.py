"""Production Secrets Management Interface — Feature #8.

Provides a unified interface for reading secrets from different backends.
In development: reads from environment variables.
In production: swappable to HashiCorp Vault or AWS SSM (both stubbed here).

Log redaction ensures no secret value ever appears in structured logs.

Usage:
    mgr = get_secrets_manager()
    api_key = mgr.get("BINANCE_API_KEY")          # raises if missing
    safe_log = redact(api_key)                     # "abcd***"
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Protocol

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Known secret keys
# ---------------------------------------------------------------------------


class SecretKey(StrEnum):
    BINANCE_API_KEY = "BINANCE_API_KEY"
    BINANCE_API_SECRET = "BINANCE_API_SECRET"
    ALPACA_API_KEY = "ALPACA_API_KEY"
    ALPACA_SECRET_KEY = "ALPACA_SECRET_KEY"
    TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
    DATABASE_URL = "DATABASE_URL"
    REDIS_URL = "REDIS_URL"
    ENCRYPTION_KEY = "ENCRYPTION_KEY"


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class SecretsProvider(Protocol):
    """Common interface for all secret backends."""

    def get(self, key: str) -> str:
        """Return secret value. Raises KeyError if not found."""
        ...

    def exists(self, key: str) -> bool:
        """Return True if the secret exists in this backend."""
        ...

    @property
    def backend_name(self) -> str:
        """Identifier for logging/audit."""
        ...


# ---------------------------------------------------------------------------
# Log redaction
# ---------------------------------------------------------------------------

_REDACT_SHOW_CHARS = 4
_REDACT_MASK = "***"


def redact(value: str) -> str:
    """Return a log-safe version of a secret value.

    Shows first 4 chars and masks the rest. Short values are fully masked.
    """
    if len(value) <= _REDACT_SHOW_CHARS:
        return _REDACT_MASK
    return value[:_REDACT_SHOW_CHARS] + _REDACT_MASK


# ---------------------------------------------------------------------------
# Environment provider (default)
# ---------------------------------------------------------------------------


class EnvSecretsProvider:
    """Reads secrets from environment variables."""

    @property
    def backend_name(self) -> str:
        return "env"

    def get(self, key: str) -> str:
        value = os.environ.get(key)
        if value is None:
            log.warning("secret_not_found", key=key, backend=self.backend_name)
            raise KeyError(f"Secret '{key}' not found in environment")
        log.debug("secret_accessed", key=key, backend=self.backend_name, preview=redact(value))
        return value

    def exists(self, key: str) -> bool:
        return key in os.environ


# ---------------------------------------------------------------------------
# Vault provider (stub — not connected)
# ---------------------------------------------------------------------------


class VaultSecretsProvider:
    """Placeholder for HashiCorp Vault integration.

    Raises NotImplementedError until the Vault agent sidecar is configured.
    """

    def __init__(self, vault_addr: str = "", vault_token: str = "") -> None:
        self._vault_addr = vault_addr
        self._vault_token = vault_token

    @property
    def backend_name(self) -> str:
        return "vault"

    def get(self, key: str) -> str:
        raise NotImplementedError(
            "VaultSecretsProvider is not yet configured. "
            f"Set VAULT_ADDR and VAULT_TOKEN, then implement the HTTP call. key={key}"
        )

    def exists(self, key: str) -> bool:
        raise NotImplementedError("VaultSecretsProvider.exists() not implemented")


# ---------------------------------------------------------------------------
# SSM provider (stub — not connected)
# ---------------------------------------------------------------------------


class SSMSecretsProvider:
    """Placeholder for AWS Systems Manager Parameter Store.

    Raises NotImplementedError until IAM role and boto3 are configured.
    """

    def __init__(self, region: str = "us-east-1", prefix: str = "/trading-bot/") -> None:
        self._region = region
        self._prefix = prefix

    @property
    def backend_name(self) -> str:
        return "ssm"

    def get(self, key: str) -> str:
        raise NotImplementedError(
            f"SSMSecretsProvider is not yet configured. region={self._region} key={key}"
        )

    def exists(self, key: str) -> bool:
        raise NotImplementedError("SSMSecretsProvider.exists() not implemented")


# ---------------------------------------------------------------------------
# Key rotation metadata
# ---------------------------------------------------------------------------


from dataclasses import dataclass  # noqa: E402
from datetime import datetime  # noqa: E402


@dataclass(frozen=True)
class RotationRecord:
    """Immutable record of a secret rotation event."""

    key: str
    rotated_at: datetime
    rotated_by: str
    backend: str
    notes: str = ""


_rotation_history: list[RotationRecord] = []


def record_rotation(
    key: str,
    rotated_by: str,
    backend: str,
    notes: str = "",
) -> RotationRecord:
    """Record a secret rotation event for audit trail."""
    from datetime import UTC
    record = RotationRecord(
        key=key,
        rotated_at=datetime.now(UTC),
        rotated_by=rotated_by,
        backend=backend,
        notes=notes,
    )
    _rotation_history.append(record)
    log.info(
        "secret_rotated",
        key=key,
        rotated_by=rotated_by,
        backend=backend,
    )
    return record


def get_rotation_history() -> list[RotationRecord]:
    return list(_rotation_history)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: SecretsProvider | None = None


def get_secrets_manager() -> SecretsProvider:
    """Return the active secrets provider (env by default)."""
    global _manager
    if _manager is None:
        _manager = EnvSecretsProvider()
    return _manager


def set_secrets_manager(provider: SecretsProvider) -> None:
    """Override the active provider (e.g., in integration tests or production bootstrap)."""
    global _manager
    _manager = provider
    log.info("secrets_manager_set", backend=provider.backend_name)
