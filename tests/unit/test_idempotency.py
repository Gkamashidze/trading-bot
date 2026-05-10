"""Unit tests for idempotency keys and store."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.idempotency.keys import idempotency_key_for_order


class TestIdempotencyKeyDeterminism:
    def test_same_inputs_same_key(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        k1 = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        k2 = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        assert k1 == k2

    def test_different_side_different_key(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        buy = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        sell = idempotency_key_for_order("sma_crossover", "BTC/USDT", "sell", today)
        assert buy != sell

    def test_different_strategy_different_key(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        k1 = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        k2 = idempotency_key_for_order("rsi_mean_reversion", "BTC/USDT", "buy", today)
        assert k1 != k2

    def test_different_symbol_different_key(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        k1 = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        k2 = idempotency_key_for_order("sma_crossover", "ETH/USDT", "buy", today)
        assert k1 != k2

    def test_different_date_different_key(self) -> None:
        k1 = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", "2026-01-01")
        k2 = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", "2026-01-02")
        assert k1 != k2

    def test_key_is_valid_uuid_format(self) -> None:
        import re

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        key = idempotency_key_for_order("sma_crossover", "BTC/USDT", "buy", today)
        uuid_pattern = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
        assert uuid_pattern.match(key), f"Key {key!r} is not a valid UUID"


class TestPostgresIdempotencyStore:
    async def test_first_acquire_returns_true(self) -> None:
        from trading_bot.idempotency.store import PostgresIdempotencyStore

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        store = PostgresIdempotencyStore(mock_pool)
        result = await store.acquire("test-key-123")
        assert result is True

    async def test_second_acquire_returns_false(self) -> None:
        from trading_bot.idempotency.store import PostgresIdempotencyStore

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 0")
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("trading_bot.idempotency.store.IDEMPOTENCY_HITS") as mock_metric:
            mock_metric.inc = MagicMock()
            store = PostgresIdempotencyStore(mock_pool)
            result = await store.acquire("already-exists-key")

        assert result is False
        mock_metric.inc.assert_called_once()

    async def test_acquire_or_raise_on_duplicate(self) -> None:
        from trading_bot.core.exceptions import IdempotencyCollisionError
        from trading_bot.idempotency.store import PostgresIdempotencyStore

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 0")
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch("trading_bot.idempotency.store.IDEMPOTENCY_HITS"):
            store = PostgresIdempotencyStore(mock_pool)
            with pytest.raises(IdempotencyCollisionError):
                await store.acquire_or_raise("duplicate-key")

    async def test_release_deletes_key(self) -> None:
        from trading_bot.idempotency.store import PostgresIdempotencyStore

        mock_pool = MagicMock()
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="DELETE 1")
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        store = PostgresIdempotencyStore(mock_pool)
        await store.release("key-to-release")

        mock_conn.execute.assert_called_once()
        call_sql = mock_conn.execute.call_args[0][0]
        assert "DELETE" in call_sql
