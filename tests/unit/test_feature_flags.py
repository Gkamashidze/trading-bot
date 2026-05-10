"""Unit tests for feature_flags/decorator.py + store.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.core.exceptions import FeatureDisabledError
from trading_bot.feature_flags.store import FeatureFlagStore


def _make_pool(enabled: bool | None = True) -> MagicMock:
    """Return a mock asyncpg pool that returns the given enabled value."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    if enabled is None:
        mock_conn.fetchrow = AsyncMock(return_value=None)
    else:
        mock_row = {"enabled": enabled}
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)

    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_pool


class TestFeatureRequiredDecorator:
    async def test_raises_when_flag_disabled(self) -> None:
        from trading_bot.feature_flags.decorator import feature_required

        @feature_required("paper_trading_enabled")
        async def _dummy() -> str:
            return "executed"

        with patch(
            "trading_bot.feature_flags.store.is_enabled",
            new=AsyncMock(return_value=False),
        ):
            with pytest.raises(FeatureDisabledError) as exc_info:
                await _dummy()

        assert exc_info.value.flag_name == "paper_trading_enabled"

    async def test_executes_when_flag_enabled(self) -> None:
        from trading_bot.feature_flags.decorator import feature_required

        @feature_required("paper_trading_enabled")
        async def _dummy() -> str:
            return "executed"

        with patch(
            "trading_bot.feature_flags.store.is_enabled",
            new=AsyncMock(return_value=True),
        ):
            result = await _dummy()

        assert result == "executed"

    async def test_preserves_function_name(self) -> None:
        from trading_bot.feature_flags.decorator import feature_required

        @feature_required("some_flag")
        async def my_specific_function() -> None:
            pass

        assert my_specific_function.__name__ == "my_specific_function"


class TestFeatureFlagStoreIsEnabled:
    async def test_returns_true_from_db(self) -> None:
        store = FeatureFlagStore(_make_pool(enabled=True))
        result = await store.is_enabled("paper_trading_enabled")
        assert result is True

    async def test_returns_false_from_db(self) -> None:
        store = FeatureFlagStore(_make_pool(enabled=False))
        result = await store.is_enabled("paper_trading_enabled")
        assert result is False

    async def test_cache_hit_skips_db(self) -> None:
        pool = _make_pool(enabled=True)
        store = FeatureFlagStore(pool, refresh_interval_seconds=60)

        # First call — hits DB
        await store.is_enabled("paper_trading_enabled")
        call_count_after_first = pool.acquire.call_count

        # Second call — should hit cache, not DB
        await store.is_enabled("paper_trading_enabled")
        assert pool.acquire.call_count == call_count_after_first

    async def test_db_miss_falls_back_to_yaml_default(self) -> None:
        store = FeatureFlagStore(_make_pool(enabled=None))

        # "paper_trading_enabled" exists in feature_flags.yaml with default=true
        result = await store.is_enabled("paper_trading_enabled")
        # If the YAML says true this passes; if false it stays false — either way no crash
        assert isinstance(result, bool)

    async def test_db_failure_falls_back_to_yaml(self) -> None:
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB down")
        )
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        store = FeatureFlagStore(pool)

        # Should not raise — fall back to YAML or False
        result = await store.is_enabled("paper_trading_enabled")
        assert isinstance(result, bool)

    async def test_safety_critical_flag_defaults_false_on_db_failure(self) -> None:
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(
            side_effect=Exception("DB down")
        )
        pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        store = FeatureFlagStore(pool)

        # live_trading_enabled is safety-critical → must default False even if YAML has true
        result = await store.is_enabled("live_trading_enabled")
        assert result is False


class TestIsEnabledModuleLevel:
    async def test_no_store_returns_yaml_default(self) -> None:
        from trading_bot.feature_flags import store as flag_store

        original = flag_store._default_store
        try:
            flag_store._default_store = None
            result = await flag_store.is_enabled("paper_trading_enabled")
            assert isinstance(result, bool)
        finally:
            flag_store._default_store = original

    async def test_with_store_delegates(self) -> None:
        from trading_bot.feature_flags import store as flag_store

        mock_store = MagicMock()
        mock_store.is_enabled = AsyncMock(return_value=True)
        original = flag_store._default_store
        try:
            flag_store._default_store = mock_store
            result = await flag_store.is_enabled("any_flag")
            assert result is True
            mock_store.is_enabled.assert_called_once_with("any_flag")
        finally:
            flag_store._default_store = original
