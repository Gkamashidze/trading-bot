"""Tests for Feature #8: Secrets Management Interface."""

from __future__ import annotations

import pytest

from trading_bot.secrets.manager import (
    EnvSecretsProvider,
    SecretKey,
    SSMSecretsProvider,
    VaultSecretsProvider,
    get_rotation_history,
    get_secrets_manager,
    record_rotation,
    redact,
    set_secrets_manager,
)


class TestRedact:
    def test_short_value_fully_masked(self) -> None:
        assert redact("ab") == "***"

    def test_exactly_four_chars_masked(self) -> None:
        assert redact("abcd") == "***"

    def test_long_value_shows_prefix(self) -> None:
        result = redact("abcde12345")
        assert result.startswith("abcd")
        assert "***" in result
        assert "12345" not in result

    def test_token_like_value(self) -> None:
        token = "1234:ABC_TOKEN_XYZ"
        result = redact(token)
        assert result == "1234***"

    def test_empty_string_masked(self) -> None:
        assert redact("") == "***"


class TestEnvSecretsProvider:
    def test_get_existing_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_SECRET_KEY", "my_secret_value")
        provider = EnvSecretsProvider()
        assert provider.get("TEST_SECRET_KEY") == "my_secret_value"

    def test_get_missing_raises_keyerror(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NONEXISTENT_SECRET_XYZ", raising=False)
        provider = EnvSecretsProvider()
        with pytest.raises(KeyError):
            provider.get("NONEXISTENT_SECRET_XYZ")

    def test_exists_true_for_set_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_KEY", "val")
        provider = EnvSecretsProvider()
        assert provider.exists("MY_KEY") is True

    def test_exists_false_for_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MISSING_KEY_ZZZ", raising=False)
        provider = EnvSecretsProvider()
        assert provider.exists("MISSING_KEY_ZZZ") is False

    def test_backend_name_is_env(self) -> None:
        assert EnvSecretsProvider().backend_name == "env"


class TestVaultSecretsProvider:
    def test_get_raises_not_implemented(self) -> None:
        provider = VaultSecretsProvider()
        with pytest.raises(NotImplementedError):
            provider.get("SOME_KEY")

    def test_exists_raises_not_implemented(self) -> None:
        provider = VaultSecretsProvider()
        with pytest.raises(NotImplementedError):
            provider.exists("SOME_KEY")

    def test_backend_name_is_vault(self) -> None:
        assert VaultSecretsProvider().backend_name == "vault"


class TestSSMSecretsProvider:
    def test_get_raises_not_implemented(self) -> None:
        provider = SSMSecretsProvider()
        with pytest.raises(NotImplementedError):
            provider.get("SOME_KEY")

    def test_backend_name_is_ssm(self) -> None:
        assert SSMSecretsProvider().backend_name == "ssm"


class TestSecretKey:
    def test_known_keys_exist(self) -> None:
        assert SecretKey.BINANCE_API_KEY == "BINANCE_API_KEY"
        assert SecretKey.TELEGRAM_BOT_TOKEN == "TELEGRAM_BOT_TOKEN"
        assert SecretKey.DATABASE_URL == "DATABASE_URL"


class TestRotationRecord:
    def test_record_rotation_appends_history(self) -> None:
        before = len(get_rotation_history())
        record_rotation("BINANCE_API_KEY", rotated_by="ops", backend="env")
        after = len(get_rotation_history())
        assert after == before + 1

    def test_rotation_record_fields(self) -> None:
        record = record_rotation("MY_KEY", rotated_by="alice", backend="vault", notes="quarterly")
        assert record.key == "MY_KEY"
        assert record.rotated_by == "alice"
        assert record.backend == "vault"
        assert record.notes == "quarterly"
        assert record.rotated_at is not None


class TestSecretsManagerSingleton:
    def test_default_is_env_provider(self) -> None:
        mgr = get_secrets_manager()
        assert mgr.backend_name == "env"

    def test_set_and_get_custom_provider(self) -> None:
        custom = EnvSecretsProvider()
        set_secrets_manager(custom)
        assert get_secrets_manager() is custom
        # Reset back to env
        set_secrets_manager(EnvSecretsProvider())
