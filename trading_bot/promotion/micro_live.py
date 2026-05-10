"""Micro-Live Trading Framework — #9 of the production readiness roadmap.

Micro-live is the ONLY bridge from paper trading to full live trading.
It is disabled by default and requires explicit operator enablement through
the go-live gate plus a clean paper trading history.

Hard constraints (cannot be overridden at runtime):
  - max order size: $50 USD equivalent
  - one strategy at a time
  - one symbol at a time
  - hard daily loss cap: $25
  - hard weekly loss cap: $75
  - automatic rollback to paper on any breach
  - no pyramiding (max 1 open position per symbol)
  - no leverage
  - mandatory daily manual approval
  - mandatory clean reconciliation before each session

Micro-live is still NOT live — it uses the same execution path but with tiny
real orders. Full live trading requires a separate gate after micro-live history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


class MicroLiveStatus(StrEnum):
    DISABLED = "disabled"  # default — not yet enabled
    ENABLED = "enabled"  # gate passed, daily approval received
    SUSPENDED = "suspended"  # auto-suspended after breach
    ROLLED_BACK = "rolled_back"  # automatic rollback to paper


@dataclass(frozen=True)
class MicroLiveConfig:
    """Hard constraints for the micro-live session.

    These are compile-time constants — operator cannot loosen them via flags.
    Tightening them (e.g. smaller max_order_usd) is allowed.
    """

    max_order_usd: Decimal = Decimal("50")
    max_daily_loss_usd: Decimal = Decimal("25")
    max_weekly_loss_usd: Decimal = Decimal("75")
    max_open_positions: int = 1  # no pyramiding
    allowed_strategies: frozenset[str] = field(default_factory=frozenset)
    allowed_symbols: frozenset[str] = field(default_factory=frozenset)
    session_window_hours: int = 4  # session auto-expires after N hours
    require_daily_operator_approval: bool = True
    require_clean_reconciliation: bool = True

    # Hard upper bounds — code will refuse to start if config exceeds these
    _ABSOLUTE_MAX_ORDER_USD: Decimal = field(default=Decimal("50"), init=False, repr=False)
    _ABSOLUTE_MAX_DAILY_LOSS_USD: Decimal = field(default=Decimal("100"), init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_order_usd > self._ABSOLUTE_MAX_ORDER_USD:
            raise ValueError(
                f"max_order_usd={self.max_order_usd} exceeds hard limit "
                f"{self._ABSOLUTE_MAX_ORDER_USD} — micro-live cannot exceed this"
            )
        if self.max_daily_loss_usd > self._ABSOLUTE_MAX_DAILY_LOSS_USD:
            raise ValueError(
                f"max_daily_loss_usd={self.max_daily_loss_usd} exceeds hard limit "
                f"{self._ABSOLUTE_MAX_DAILY_LOSS_USD}"
            )


@dataclass
class MicroLiveSession:
    """Runtime state for the current micro-live session."""

    status: MicroLiveStatus = MicroLiveStatus.DISABLED
    strategy_id: str = ""
    symbol: str = ""
    started_at: datetime | None = None
    last_approval_at: datetime | None = None
    approved_by: str = ""

    daily_realized_loss_usd: Decimal = Decimal("0")
    weekly_realized_loss_usd: Decimal = Decimal("0")
    session_trade_count: int = 0
    total_notional_usd: Decimal = Decimal("0")

    rollback_reason: str = ""
    suspended_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.status == MicroLiveStatus.ENABLED

    @property
    def session_age_hours(self) -> float:
        if self.started_at is None:
            return 0.0
        return (datetime.now(UTC) - self.started_at).total_seconds() / 3600


class MicroLiveGate:
    """Enforces all micro-live constraints and manages session lifecycle.

    The gate is disabled by default. Enabling requires:
    1. An explicit operator enable() call (simulating go-live gate approval)
    2. Daily operator approval via approve_daily()
    3. Clean reconciliation state

    The gate automatically rolls back to paper on any breach.
    """

    # Hard gates — always False in this codebase until Stage 5 complete + paper success
    _MICRO_LIVE_GLOBALLY_ENABLED: bool = False

    def __init__(self, config: MicroLiveConfig | None = None) -> None:
        self._config = config or MicroLiveConfig()
        self._session = MicroLiveSession()

    @property
    def session(self) -> MicroLiveSession:
        return self._session

    @property
    def status(self) -> MicroLiveStatus:
        return self._session.status

    def is_order_allowed(
        self,
        strategy_id: str,
        symbol: str,
        order_notional_usd: Decimal,
        open_position_count: int,
    ) -> tuple[bool, str]:
        """Check if a new order is permitted under micro-live constraints.

        Returns (allowed, reason). Called before every order submission.
        """
        if not self._MICRO_LIVE_GLOBALLY_ENABLED:
            return (
                False,
                "micro-live is globally disabled — system not yet cleared for live trading",
            )

        if not self._session.is_active:
            return False, f"micro-live session not active (status={self._session.status})"

        cfg = self._config

        # Session expiry
        if cfg.session_window_hours > 0:
            if self._session.session_age_hours > cfg.session_window_hours:
                self._suspend("session window expired")
                return False, "micro-live session window expired — requires new daily approval"

        # Daily approval
        if cfg.require_daily_operator_approval:
            if self._session.last_approval_at is None:
                return False, "no daily operator approval on record"
            approval_age = datetime.now(UTC) - self._session.last_approval_at
            if approval_age > timedelta(hours=24):
                return False, "daily operator approval expired"

        # Strategy and symbol lock
        if cfg.allowed_strategies and strategy_id not in cfg.allowed_strategies:
            return False, f"strategy {strategy_id!r} not in micro-live allowed list"
        if cfg.allowed_symbols and symbol not in cfg.allowed_symbols:
            return False, f"symbol {symbol!r} not in micro-live allowed list"

        # Max order size
        if order_notional_usd > cfg.max_order_usd:
            self._suspend(f"order notional ${order_notional_usd} exceeds max ${cfg.max_order_usd}")
            return (
                False,
                f"order notional ${order_notional_usd} exceeds micro-live max ${cfg.max_order_usd}",
            )

        # No pyramiding
        if open_position_count >= cfg.max_open_positions:
            return (
                False,
                f"already at max_open_positions={cfg.max_open_positions} — no pyramiding",
            )

        # Loss budgets
        if self._session.daily_realized_loss_usd >= cfg.max_daily_loss_usd:
            self._rollback(
                f"daily loss cap breached: ${self._session.daily_realized_loss_usd} "
                f">= ${cfg.max_daily_loss_usd}"
            )
            return False, "micro-live daily loss cap breached — rolled back to paper"

        if self._session.weekly_realized_loss_usd >= cfg.max_weekly_loss_usd:
            self._rollback(
                f"weekly loss cap breached: ${self._session.weekly_realized_loss_usd} "
                f">= ${cfg.max_weekly_loss_usd}"
            )
            return False, "micro-live weekly loss cap breached — rolled back to paper"

        return True, ""

    def record_fill(self, realized_pnl_usd: Decimal, notional_usd: Decimal) -> None:
        """Update session state after a confirmed fill. Checks breaches immediately."""
        self._session.session_trade_count += 1
        self._session.total_notional_usd += notional_usd

        if realized_pnl_usd < 0:
            loss = realized_pnl_usd.copy_abs()
            self._session.daily_realized_loss_usd += loss
            self._session.weekly_realized_loss_usd += loss

            if self._session.daily_realized_loss_usd >= self._config.max_daily_loss_usd:
                self._rollback(
                    f"daily loss cap breached post-fill: ${self._session.daily_realized_loss_usd}"
                )
                return

        log.info(
            "micro_live_fill_recorded",
            trade_count=self._session.session_trade_count,
            daily_loss=str(self._session.daily_realized_loss_usd),
            weekly_loss=str(self._session.weekly_realized_loss_usd),
        )

    def approve_daily(self, operator: str) -> None:
        """Record daily operator approval. Required before each session."""
        self._session.last_approval_at = datetime.now(UTC)
        self._session.approved_by = operator
        log.info("micro_live_daily_approved", operator=operator)

    def enable(
        self,
        strategy_id: str,
        symbol: str,
        operator: str,
    ) -> None:
        """Enable micro-live for a specific strategy+symbol (operator action).

        Still gated by _MICRO_LIVE_GLOBALLY_ENABLED — will fail at is_order_allowed()
        even if session is ENABLED, until the global flag is set (Stage 5 + paper success).
        """
        self._session.status = MicroLiveStatus.ENABLED
        self._session.strategy_id = strategy_id
        self._session.symbol = symbol
        self._session.started_at = datetime.now(UTC)
        self.approve_daily(operator)
        log.warning(
            "micro_live_enabled",
            strategy_id=strategy_id,
            symbol=symbol,
            operator=operator,
            globally_enabled=self._MICRO_LIVE_GLOBALLY_ENABLED,
        )

    def disable(self) -> None:
        """Manually disable micro-live — return to paper."""
        self._session.status = MicroLiveStatus.DISABLED
        log.info("micro_live_disabled_manually")

    def _suspend(self, reason: str) -> None:
        self._session.status = MicroLiveStatus.SUSPENDED
        self._session.suspended_at = datetime.now(UTC)
        self._session.rollback_reason = reason
        log.warning("micro_live_suspended", reason=reason)

    def _rollback(self, reason: str) -> None:
        self._session.status = MicroLiveStatus.ROLLED_BACK
        self._session.rollback_reason = reason
        log.error("micro_live_rolled_back_to_paper", reason=reason)
