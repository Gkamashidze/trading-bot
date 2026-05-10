"""Tests for Stage 7 Operator Console: TelegramCommandHandler."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trading_bot.operator_console.telegram_commands import TelegramCommandHandler


def _make_handler(authorized_chat_id: int = 123456) -> TelegramCommandHandler:
    pool = MagicMock()
    return TelegramCommandHandler(
        token="test_token",
        authorized_chat_id=authorized_chat_id,
        pool=pool,
    )


def _make_snapshot_mock(equity: float = 10_000.0) -> MagicMock:
    snap = MagicMock()
    snap.total_equity = Decimal(str(equity))
    snap.cash_balance = Decimal(str(equity * 0.9))
    snap.daily_pnl = Decimal("50")
    snap.daily_drawdown_pct = Decimal("-0.005")
    snap.positions = []
    return snap


class TestFromEnvOptional:
    def test_returns_none_when_no_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_ALERT_CHAT_ID", raising=False)
        result = TelegramCommandHandler.from_env_optional(pool=MagicMock())
        assert result is None

    def test_returns_handler_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc:123")
        monkeypatch.setenv("TELEGRAM_ALERT_CHAT_ID", "999")
        result = TelegramCommandHandler.from_env_optional(pool=MagicMock())
        assert result is not None
        assert result._authorized_chat_id == 999

    def test_returns_none_on_invalid_chat_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc:123")
        monkeypatch.setenv("TELEGRAM_ALERT_CHAT_ID", "not_an_int")
        result = TelegramCommandHandler.from_env_optional(pool=MagicMock())
        assert result is None


class TestCommandDispatch:
    @pytest.mark.asyncio
    async def test_status_sends_reply(self) -> None:
        handler = _make_handler()
        client = AsyncMock()
        handler._send = AsyncMock()
        await handler._cmd_status(client, 123456)
        handler._send.assert_awaited_once()
        text = handler._send.await_args[0][2]
        assert "სტატუსი" in text or "Uptime" in text

    @pytest.mark.asyncio
    async def test_portfolio_sends_equity(self) -> None:
        handler = _make_handler()
        client = AsyncMock()
        handler._send = AsyncMock()
        pm = MagicMock()
        pm.get_snapshot.return_value = _make_snapshot_mock(equity=15_000.0)
        with patch("trading_bot.portfolio.manager.get_portfolio_manager", return_value=pm):
            await handler._cmd_portfolio(client, 123456)
        text = handler._send.await_args[0][2]
        assert "15" in text  # equity value appears

    @pytest.mark.asyncio
    async def test_circuit_breaker_shows_tier(self) -> None:
        handler = _make_handler()
        client = AsyncMock()
        handler._send = AsyncMock()
        cb = MagicMock()
        cb.label = "ჯანმრთელი"
        cb.is_trading_allowed.return_value = True
        cb.last_drawdown_pct = 0.03
        cb.peak_tier_today = 0
        cb.last_checked = None
        with patch("trading_bot.safety.circuit_breaker.get_circuit_breaker", return_value=cb):
            await handler._cmd_circuit_breaker(client, 123456)
        text = handler._send.await_args[0][2]
        assert "Circuit Breaker" in text or "cb" in text.lower() or "დონე" in text

    @pytest.mark.asyncio
    async def test_kill_no_pool_sends_error(self) -> None:
        handler = _make_handler()
        handler._pool = None
        client = AsyncMock()
        handler._send = AsyncMock()
        await handler._cmd_kill(client, 123456)
        text = handler._send.await_args[0][2]
        assert "DB" in text or "❌" in text

    @pytest.mark.asyncio
    async def test_kill_with_pool_toggles_flag(self) -> None:
        handler = _make_handler()
        client = AsyncMock()
        handler._send = AsyncMock()

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"enabled": True})
        handler._pool.acquire = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        await handler._cmd_kill(client, 123456)
        mock_conn.fetchrow.assert_awaited_once()
        text = handler._send.await_args[0][2]
        assert "ვაჭრობა" in text

    @pytest.mark.asyncio
    async def test_kill_flag_not_found(self) -> None:
        handler = _make_handler()
        client = AsyncMock()
        handler._send = AsyncMock()

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        handler._pool.acquire = MagicMock(
            return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_conn),
                __aexit__=AsyncMock(return_value=False),
            )
        )

        await handler._cmd_kill(client, 123456)
        text = handler._send.await_args[0][2]
        assert "❌" in text

    @pytest.mark.asyncio
    async def test_unknown_command_sends_help_hint(self) -> None:
        handler = _make_handler()
        client = AsyncMock()
        handler._send = AsyncMock()
        await handler._dispatch(client, 123456, "unknown_cmd", [])
        text = handler._send.await_args[0][2]
        assert "help" in text or "ბრძანება" in text

    @pytest.mark.asyncio
    async def test_help_lists_commands(self) -> None:
        handler = _make_handler()
        client = AsyncMock()
        handler._send = AsyncMock()
        await handler._cmd_help(client, 123456)
        text = handler._send.await_args[0][2]
        assert "/status" in text
        assert "/kill" in text


class TestPollFiltering:
    @pytest.mark.asyncio
    async def test_unauthorized_chat_id_is_ignored(self) -> None:
        handler = _make_handler(authorized_chat_id=111111)
        handler._dispatch = AsyncMock()

        update = {
            "update_id": 1,
            "message": {
                "chat": {"id": 999999},  # different chat
                "text": "/status",
            },
        }
        client = AsyncMock()
        client.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                json=lambda: {"ok": True, "result": [update]},
            )
        )

        await handler._poll_once(client)
        handler._dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_authorized_chat_dispatches_command(self) -> None:
        handler = _make_handler(authorized_chat_id=123456)
        handler._dispatch = AsyncMock()

        update = {
            "update_id": 5,
            "message": {
                "chat": {"id": 123456},
                "text": "/status",
            },
        }
        client = AsyncMock()
        client.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                json=lambda: {"ok": True, "result": [update]},
            )
        )

        await handler._poll_once(client)
        handler._dispatch.assert_awaited_once_with(client, 123456, "status", [])

    @pytest.mark.asyncio
    async def test_offset_updated_after_processing(self) -> None:
        handler = _make_handler()
        handler._dispatch = AsyncMock()

        update = {
            "update_id": 42,
            "message": {"chat": {"id": 123456}, "text": "/help"},
        }
        client = AsyncMock()
        client.get = AsyncMock(
            return_value=MagicMock(
                status_code=200,
                json=lambda: {"ok": True, "result": [update]},
            )
        )

        await handler._poll_once(client)
        assert handler._offset == 43  # update_id + 1
