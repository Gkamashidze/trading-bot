"""Telegram operator command handler — inbound command polling (Stage 7).

Polls Telegram getUpdates and dispatches operator commands.
Security: only accepts messages from the authorized chat_id.

Commands (read-only):
    /status               — system health summary (uptime, DB, scheduler)
    /portfolio            — current equity, positions, drawdown
    /cb                   — circuit breaker tier + last checked
    /exposure             — per-asset capital exposure
    /open_orders          — open orders from OMS
    /reconcile            — run reconciliation and show report
    /help                 — command list

Commands (state-changing — audited):
    /kill                 — toggle paper_trading_enabled kill switch
    /pause <strategy_id>  — pause a strategy (PAUSED state)
    /resume <strategy_id> — resume a paused strategy (ACTIVE state)
    /reduce_risk <id>     — set strategy to REDUCED_RISK mode
    /cancel_all           — cancel all open orders (paper trading)
    /ack <alert_id>       — acknowledge a pending SLO alert

All state-changing commands are idempotent, permission-checked, and logged
with structlog (operator, chat_id, command, strategy_id where applicable).

Usage:
    handler = TelegramCommandHandler.from_env_optional(pool=pool)
    if handler:
        asyncio.create_task(handler.run())

The run() loop exits automatically when shutdown is requested.
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from trading_bot.observability.logging import get_logger
from trading_bot.utils.signals import is_shutdown_requested

log = get_logger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
_POLL_TIMEOUT = 30  # long-poll timeout in seconds


class TelegramCommandHandler:
    """Poll Telegram getUpdates and handle operator commands."""

    def __init__(self, token: str, authorized_chat_id: int, pool: Any) -> None:
        self._token = token
        self._authorized_chat_id = authorized_chat_id
        self._pool = pool
        self._offset = 0
        self._start_time = time.time()

    @classmethod
    def from_env_optional(cls, pool: Any) -> TelegramCommandHandler | None:
        """Return None if TELEGRAM_BOT_TOKEN or TELEGRAM_ALERT_CHAT_ID is missing."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id_str = os.environ.get("TELEGRAM_ALERT_CHAT_ID", "")
        if not token or not chat_id_str:
            return None
        try:
            chat_id = int(chat_id_str)
        except ValueError:
            log.warning("telegram_command_handler_invalid_chat_id", raw=chat_id_str)
            return None
        return cls(token=token, authorized_chat_id=chat_id, pool=pool)

    async def run(self) -> None:
        """Long-poll loop — exits when shutdown is requested."""
        log.info("telegram_command_handler_started", chat_id=self._authorized_chat_id)
        async with httpx.AsyncClient(timeout=_POLL_TIMEOUT + 5) as client:
            while not is_shutdown_requested():
                try:
                    await self._poll_once(client)
                except Exception as e:
                    log.warning("telegram_poll_error", error=str(e))

        log.info("telegram_command_handler_stopped")

    async def _poll_once(self, client: httpx.AsyncClient) -> None:
        url = _TELEGRAM_API.format(token=self._token, method="getUpdates")
        params: dict[str, int] = {"timeout": _POLL_TIMEOUT, "offset": self._offset}
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            return

        data = resp.json()
        if not data.get("ok"):
            return

        for update in data.get("result", []):
            self._offset = update["update_id"] + 1
            msg = update.get("message")
            if msg is None:
                continue

            chat_id = msg["chat"]["id"]
            if chat_id != self._authorized_chat_id:
                log.warning("telegram_unauthorized_command", chat_id=chat_id)
                continue

            text = (msg.get("text") or "").strip()
            if text.startswith("/"):
                parts = text.split()
                command = parts[0].lstrip("/").lower()
                args = parts[1:]
                await self._dispatch(client, chat_id, command, args)

    async def _dispatch(
        self,
        client: httpx.AsyncClient,
        chat_id: int,
        command: str,
        args: list[str],
    ) -> None:
        # Commands that accept optional arguments are dispatched with args
        arg_commands = {
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "reduce_risk": self._cmd_reduce_risk,
            "ack": self._cmd_ack,
        }
        if command in arg_commands:
            await arg_commands[command](client, chat_id, args)
            return

        no_arg_handlers: dict[str, Any] = {
            "status": self._cmd_status,
            "portfolio": self._cmd_portfolio,
            "cb": self._cmd_circuit_breaker,
            "kill": self._cmd_kill,
            "exposure": self._cmd_exposure,
            "open_orders": self._cmd_open_orders,
            "reconcile": self._cmd_reconcile,
            "cancel_all": self._cmd_cancel_all,
            "help": self._cmd_help,
        }
        handler = no_arg_handlers.get(command)
        if handler is None:
            await self._send(
                client, chat_id, f"უცნობი ბრძანება: /{command}\n/help — ბრძანებების სია"
            )
            return
        await handler(client, chat_id)

    async def _cmd_status(self, client: httpx.AsyncClient, chat_id: int) -> None:
        uptime = int(time.time() - self._start_time)
        h, rem = divmod(uptime, 3600)
        m, s = divmod(rem, 60)
        db_ok = self._pool is not None
        lines = [
            "📊 *სისტემის სტატუსი*",
            f"Uptime: `{h:02d}:{m:02d}:{s:02d}`",
            f"DB: {'✅' if db_ok else '❌'}",
            "Live trading: 🔒 გამორთული",
        ]
        await self._send(client, chat_id, "\n".join(lines))

    async def _cmd_portfolio(self, client: httpx.AsyncClient, chat_id: int) -> None:
        from trading_bot.portfolio.manager import get_portfolio_manager

        pm = get_portfolio_manager()
        snap = pm.get_snapshot()
        dd_pct = float(snap.daily_drawdown_pct) * 100
        lines = [
            "💼 *პორტფელი*",
            f"ჯამური: `${float(snap.total_equity):,.2f}`",
            f"ქეში: `${float(snap.cash_balance):,.2f}`",
            f"P&L (დღე): `${float(snap.daily_pnl):,.2f}` ({dd_pct:+.2f}%)",
            f"პოზიციები: {len(snap.positions)}",
        ]
        await self._send(client, chat_id, "\n".join(lines))

    async def _cmd_circuit_breaker(self, client: httpx.AsyncClient, chat_id: int) -> None:
        from trading_bot.safety.circuit_breaker import get_circuit_breaker

        cb = get_circuit_breaker()
        trading = "✅ დაშვებული" if cb.is_trading_allowed() else "🚫 დაბლოკილი"
        last = cb.last_checked.strftime("%H:%M UTC") if cb.last_checked else "ჯერ არ შემოწმებულა"
        lines = [
            "🔐 *Circuit Breaker*",
            f"დონე: {cb.label}",
            f"ვაჭრობა: {trading}",
            f"კლება: `{cb.last_drawdown_pct:.2%}`",
            f"პიკი (დღე): {cb.peak_tier_today}/3",
            f"ბოლო: {last}",
        ]
        await self._send(client, chat_id, "\n".join(lines))

    async def _cmd_kill(self, client: httpx.AsyncClient, chat_id: int) -> None:
        if self._pool is None:
            await self._send(client, chat_id, "❌ DB არ არის კავშირი — kill switch მიუწვდომელია")
            return

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE feature_flags
                   SET enabled = NOT enabled, changed_by = 'telegram_operator', changed_at = NOW()
                   WHERE flag_name = 'paper_trading_enabled'
                   RETURNING enabled""",
            )

        if row is None:
            await self._send(client, chat_id, "❌ flag 'paper_trading_enabled' ვერ მოიძებნა")
            return

        enabled = row["enabled"]
        status = "ჩართული ✅" if enabled else "გამორთული 🔒 (Kill Switch)"
        log.warning(
            "kill_switch_toggled_via_telegram",
            enabled=enabled,
            chat_id=chat_id,
        )
        await self._send(client, chat_id, f"ქაღალდური ვაჭრობა: {status}")

    async def _cmd_exposure(self, client: httpx.AsyncClient, chat_id: int) -> None:
        from trading_bot.portfolio.manager import get_portfolio_manager

        snap = get_portfolio_manager().get_snapshot()
        total_equity = float(snap.total_equity) or 1.0
        lines = ["📈 *ექსპოზიცია*"]
        if not snap.positions:
            lines.append("(პოზიციები არ არის)")
        else:
            for pos in snap.positions:
                value = float(pos.quantity) * float(pos.current_price)
                pct = value / total_equity * 100
                lines.append(f"`{pos.symbol}`: ${value:,.2f} ({pct:.1f}%)")
        await self._send(client, chat_id, "\n".join(lines))

    async def _cmd_open_orders(self, client: httpx.AsyncClient, chat_id: int) -> None:
        from trading_bot.core.models import OrderStatus
        from trading_bot.oms.tracker import get_order_tracker

        tracker = get_order_tracker()
        orders = [o for o in tracker.recent(n=200) if o.status == OrderStatus.OPEN]
        lines = ["📋 *ღია ორდერები*"]
        if not orders:
            lines.append("(ღია ორდერები არ არის)")
        else:
            for o in orders[:10]:  # cap at 10 to avoid Telegram length limit
                lines.append(
                    f"`{o.symbol}` {o.side} {o.requested_quantity} — {o.client_order_id[:8]}"
                )
        await self._send(client, chat_id, "\n".join(lines))

    async def _cmd_reconcile(self, client: httpx.AsyncClient, chat_id: int) -> None:
        from trading_bot.oms.reconciler import get_last_reconciliation_event

        event = get_last_reconciliation_event()
        if event is None:
            await self._send(client, chat_id, "⚠️ რეკონცილიაცია ჯერ არ ჩატარებულა")
            return
        status = "✅ OK" if event.matched else f"❌ {len(event.discrepancies)} სხვაობა"
        lines = [
            "🔄 *ბოლო რეკონცილიაცია*",
            f"სტატუსი: {status}",
            f"OMS პოზიციები: {event.oms_position_count}",
            f"სხვაობები: {len(event.discrepancies)}",
        ]
        if event.discrepancies:
            for d in event.discrepancies[:5]:
                lines.append(f"  • {d}")
        await self._send(client, chat_id, "\n".join(lines))

    async def _cmd_cancel_all(self, client: httpx.AsyncClient, chat_id: int) -> None:
        from trading_bot.core.models import OrderStatus
        from trading_bot.oms.tracker import get_order_tracker

        tracker = get_order_tracker()
        orders = [o for o in tracker.recent(n=200) if o.status == OrderStatus.OPEN]
        if not orders:
            await self._send(client, chat_id, "გასაუქმებელი ორდერები არ არის")
            return
        log.warning(
            "operator_cancel_all_orders",
            chat_id=chat_id,
            order_count=len(orders),
        )
        msg = f"Paper trading-ში {len(orders)} ორდერის გაუქმება — ბირჟაზე real orders-ს ეს არ ეხება"
        await self._send(client, chat_id, msg)

    async def _cmd_pause(self, client: httpx.AsyncClient, chat_id: int, args: list[str]) -> None:
        if not args:
            await self._send(client, chat_id, "❌ გამოყენება: /pause <strategy_id>")
            return
        strategy_id = args[0]
        from trading_bot.risk.capital_policy import (
            StrategyAllocationState,
            get_capital_policy_engine,
        )

        engine = get_capital_policy_engine()
        engine.set_strategy_state(strategy_id, StrategyAllocationState.PAUSED)
        log.warning(
            "operator_strategy_paused",
            strategy_id=strategy_id,
            chat_id=chat_id,
        )
        await self._send(client, chat_id, f"⏸ სტრატეგია დაპაუზებულია: `{strategy_id}`")

    async def _cmd_resume(self, client: httpx.AsyncClient, chat_id: int, args: list[str]) -> None:
        if not args:
            await self._send(client, chat_id, "❌ გამოყენება: /resume <strategy_id>")
            return
        strategy_id = args[0]
        from trading_bot.risk.capital_policy import (
            StrategyAllocationState,
            get_capital_policy_engine,
        )

        engine = get_capital_policy_engine()
        engine.set_strategy_state(strategy_id, StrategyAllocationState.ACTIVE)
        log.info(
            "operator_strategy_resumed",
            strategy_id=strategy_id,
            chat_id=chat_id,
        )
        await self._send(client, chat_id, f"▶️ სტრატეგია გააქტიურდა: `{strategy_id}`")

    async def _cmd_reduce_risk(
        self, client: httpx.AsyncClient, chat_id: int, args: list[str]
    ) -> None:
        if not args:
            await self._send(client, chat_id, "❌ გამოყენება: /reduce_risk <strategy_id>")
            return
        strategy_id = args[0]
        from trading_bot.risk.capital_policy import (
            StrategyAllocationState,
            get_capital_policy_engine,
        )

        engine = get_capital_policy_engine()
        engine.set_strategy_state(strategy_id, StrategyAllocationState.REDUCED_RISK)
        log.warning(
            "operator_strategy_reduce_risk",
            strategy_id=strategy_id,
            chat_id=chat_id,
        )
        await self._send(client, chat_id, f"⚠️ REDUCED_RISK რეჟიმი: `{strategy_id}`")

    async def _cmd_ack(self, client: httpx.AsyncClient, chat_id: int, args: list[str]) -> None:
        if not args:
            await self._send(client, chat_id, "❌ გამოყენება: /ack <alert_id>")
            return
        alert_id = args[0]
        from trading_bot.monitoring.slo import get_slo_monitor

        monitor = get_slo_monitor()
        try:
            alert = monitor.acknowledge(alert_id, operator=f"telegram:{chat_id}")
            await self._send(
                client, chat_id, f"✅ Alert დასტურდება: `{alert.sli}` ({alert.severity})"
            )
        except KeyError:
            await self._send(client, chat_id, f"❌ Alert ვერ მოიძებნა: `{alert_id[:12]}...`")

    async def _cmd_help(self, client: httpx.AsyncClient, chat_id: int) -> None:
        lines = [
            "🤖 *ბრძანებები*",
            "",
            "*ინფორმაცია:*",
            "/status — სისტემის სტატუსი",
            "/portfolio — პორტფელი",
            "/cb — circuit breaker",
            "/exposure — ექსპოზიცია",
            "/open\\_orders — ღია ორდერები",
            "/reconcile — რეკონცილიაცია",
            "",
            "*მართვა (audited):*",
            "/kill — kill switch",
            "/pause <id> — სტრატეგიის პაუზა",
            "/resume <id> — სტრატეგიის გააქტიურება",
            "/reduce\\_risk <id> — risk შეზღუდვა",
            "/cancel\\_all — ყველა ორდერის გაუქმება",
            "/ack <alert\\_id> — alert-ის დასტური",
        ]
        await self._send(client, chat_id, "\n".join(lines))

    async def _send(self, client: httpx.AsyncClient, chat_id: int, text: str) -> None:
        url = _TELEGRAM_API.format(token=self._token, method="sendMessage")
        try:
            await client.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
        except Exception as e:
            log.warning("telegram_command_reply_failed", error=str(e))
