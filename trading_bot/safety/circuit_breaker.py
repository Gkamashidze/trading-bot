"""Safety circuit breaker — monitors daily drawdown and halts trading on tier breaches.

Tier thresholds (from RiskSettings):
    Tier 1 (default 5%)  — pause new orders
    Tier 2 (default 10%) — full halt
    Tier 3 (default 15%) — emergency halt + Telegram alert

State resets at UTC midnight via daily_portfolio_reset_job().

The circuit breaker is a module-level singleton. All state lives in
the asyncio event loop — no locking required.
"""

from __future__ import annotations

from datetime import UTC, datetime

from trading_bot.config import get_settings
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_TIER_ACTIONS = {
    1: "pause_new",
    2: "full_halt",
    3: "emergency_halt",
}

_TIER_LABELS_GE = {
    0: "ჯანმრთელი",
    1: "I დონე — პაუზა",
    2: "II დონე — სრული გაჩერება",
    3: "III დონე — საგანგებო",
}


class CircuitBreaker:
    """Drawdown-based circuit breaker for the paper trading engine.

    Call check() periodically (every 5 min via scheduler).
    Call is_trading_allowed() before routing any order.
    Call reset_day() at UTC midnight.
    """

    def __init__(self) -> None:
        self._current_tier: int = 0
        self._peak_tier_today: int = 0
        self._last_drawdown_pct: float = 0.0
        self._last_checked: datetime | None = None
        self._tripped_at: datetime | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def check(self) -> int:
        """Re-evaluate drawdown against tier thresholds.

        Returns the current tier (0 = healthy, 1-3 = breached).
        Sends Telegram alerts on NEW tier crossings only.
        """
        from trading_bot.portfolio.manager import get_portfolio_manager

        portfolio = get_portfolio_manager()
        snapshot = portfolio.get_snapshot()
        drawdown_pct = float(abs(snapshot.daily_drawdown_pct))

        risk = get_settings().risk
        new_tier = self._compute_tier(
            drawdown_pct,
            risk.tier1_daily_drawdown_pct,
            risk.tier2_daily_drawdown_pct,
            risk.tier3_daily_drawdown_pct,
        )

        self._last_drawdown_pct = drawdown_pct
        self._last_checked = datetime.now(UTC)

        if new_tier > self._current_tier:
            action = self._trip(new_tier, drawdown_pct)
            await _send_tier_alert(new_tier, drawdown_pct, action)

        self._current_tier = new_tier
        return new_tier

    def is_trading_allowed(self) -> bool:
        """Return False when tier >= 2 (full halt or emergency)."""
        return self._current_tier < 2

    def reset_day(self) -> None:
        """Reset for a new trading day (call at UTC midnight)."""
        prev_tier = self._current_tier
        self._current_tier = 0
        self._peak_tier_today = 0
        self._last_drawdown_pct = 0.0
        self._tripped_at = None
        log.info(
            "circuit_breaker_day_reset",
            previous_tier=prev_tier,
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def current_tier(self) -> int:
        return self._current_tier

    @property
    def peak_tier_today(self) -> int:
        return self._peak_tier_today

    @property
    def last_drawdown_pct(self) -> float:
        return self._last_drawdown_pct

    @property
    def last_checked(self) -> datetime | None:
        return self._last_checked

    @property
    def tripped_at(self) -> datetime | None:
        return self._tripped_at

    @property
    def label(self) -> str:
        return _TIER_LABELS_GE.get(self._current_tier, str(self._current_tier))

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_tier(
        drawdown_pct: float,
        t1: float,
        t2: float,
        t3: float,
    ) -> int:
        if drawdown_pct >= t3:
            return 3
        if drawdown_pct >= t2:
            return 2
        if drawdown_pct >= t1:
            return 1
        return 0

    def _trip(self, new_tier: int, drawdown_pct: float) -> str:
        """Handle a new tier crossing — log and set state. Returns action string."""
        self._peak_tier_today = max(self._peak_tier_today, new_tier)
        if self._tripped_at is None:
            self._tripped_at = datetime.now(UTC)

        action = _TIER_ACTIONS[new_tier]
        log.error(
            "circuit_breaker_tripped",
            tier=new_tier,
            drawdown_pct=f"{drawdown_pct:.2%}",
            action=action,
        )
        return action


async def _send_tier_alert(tier: int, drawdown_pct: float, action: str) -> None:
    from trading_bot.alerts.telegram import TelegramAlerter

    alerter = TelegramAlerter.from_env_optional()
    if alerter is None:
        return
    await alerter.send_circuit_breaker_alert(tier, drawdown_pct, action)


# ── Module-level singleton ────────────────────────────────────────────────────

_circuit_breaker: CircuitBreaker | None = None


def get_circuit_breaker() -> CircuitBreaker:
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker
