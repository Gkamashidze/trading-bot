"""Telegram alert sender - one-way notifications only (Stage 0-6).

Uses httpx (already a dependency) to call the Telegram Bot API directly.
No aiogram needed for outbound-only alerts.

Interactive commands (kill switch via Telegram) are Stage 7+.

Usage:
    from trading_bot.alerts.telegram import TelegramAlerter, AlertLevel

    alerter = TelegramAlerter.from_env()
    await alerter.send(AlertLevel.ERROR, "Job failed", detail="ingestion timeout")
"""

from __future__ import annotations

import os
from enum import StrEnum

import httpx

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

# Telegram Bot API base URL — never changes
_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"

# Max message length Telegram allows
_MAX_MSG_LEN = 4096


class AlertLevel(StrEnum):
    INFO = "INFO"
    SUCCESS = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


_LEVEL_EMOJI = {
    AlertLevel.INFO: "ℹ️",  # noqa: RUF001
    AlertLevel.SUCCESS: "✅",
    AlertLevel.WARNING: "⚠️",
    AlertLevel.ERROR: "❌",
    AlertLevel.CRITICAL: "🔴",
}


class TelegramAlerter:
    """Send formatted alert messages to a Telegram chat."""

    def __init__(self, token: str, chat_id: str) -> None:
        self._token = token
        self._chat_id = chat_id
        self._url = _TELEGRAM_API_BASE.format(token=token)

    @classmethod
    def from_env(cls) -> TelegramAlerter:
        """Build from TELEGRAM_BOT_TOKEN + TELEGRAM_ALERT_CHAT_ID env vars."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_ALERT_CHAT_ID", "")
        if not token or not chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID must be set")
        return cls(token=token, chat_id=chat_id)

    @classmethod
    def from_env_optional(cls) -> TelegramAlerter | None:
        """Return None if env vars are missing (bot runs without Telegram alerts)."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_ALERT_CHAT_ID", "")
        if not token or not chat_id:
            return None
        return cls(token=token, chat_id=chat_id)

    async def send(
        self,
        level: AlertLevel,
        title: str,
        detail: str = "",
        *,
        disable_notification: bool = False,
    ) -> bool:
        """Send an alert. Returns True on success, False on failure (never raises)."""
        emoji = _LEVEL_EMOJI[level]
        lines = [f"<b>{emoji} {level.value} — Trading Bot</b>", f"<b>{title}</b>"]
        if detail:
            lines.append(f"<code>{detail[:500]}</code>")

        text = "\n".join(lines)
        if len(text) > _MAX_MSG_LEN:
            text = text[: _MAX_MSG_LEN - 3] + "..."

        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": disable_notification,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._url, json=payload)
                resp.raise_for_status()
                log.info("telegram_alert_sent", level=level.value, title=title)
                return True
        except httpx.HTTPStatusError as e:
            log.error(
                "telegram_alert_failed",
                status=e.response.status_code,
                body=e.response.text[:200],
            )
        except httpx.RequestError as e:
            log.error("telegram_alert_network_error", error=str(e))
        return False

    async def send_job_failed(self, job_name: str, error: str) -> bool:
        return await self.send(
            AlertLevel.ERROR,
            f"Job failed: {job_name}",
            detail=error,
        )

    async def send_job_success(self, job_name: str, detail: str = "") -> bool:
        return await self.send(
            AlertLevel.SUCCESS,
            f"Job complete: {job_name}",
            detail=detail,
            disable_notification=True,  # success = silent notification
        )

    async def send_drawdown_alert(self, symbol: str, drawdown_pct: float) -> bool:
        return await self.send(
            AlertLevel.WARNING,
            f"Drawdown alert: {symbol}",
            detail=f"Current drawdown: {drawdown_pct:.2f}%",
        )

    async def send_startup(self, environment: str, stage: str) -> bool:
        return await self.send(
            AlertLevel.INFO,
            "Trading bot started",
            detail=f"environment={environment}  stage={stage}  live_trading=DISABLED",
            disable_notification=True,
        )

    async def send_shutdown(self) -> bool:
        return await self.send(AlertLevel.WARNING, "Trading bot stopped")

    async def send_circuit_breaker_alert(
        self,
        tier: int,
        drawdown_pct: float,
        action: str,
    ) -> bool:
        level = AlertLevel.CRITICAL if tier >= 3 else AlertLevel.WARNING
        tier_labels = {
            1: "I დონე — შეჩერება",
            2: "II დონე — სრული გაჩერება",
            3: "III დონე — საგანგებო",
        }
        label = tier_labels.get(tier, f"დონე {tier}")
        detail = (
            f"დეკლანი: {drawdown_pct:.2%} | ქმედება: {action}\n"
            f"ქაღალდური ვაჭრობა დაბლოკილია ახალი სავაჭრო დღის გათენებამდე."
        )
        return await self.send(
            level,
            f"Circuit Breaker: {label}",
            detail=detail,
        )
