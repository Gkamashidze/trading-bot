"""Pre-Trade Compliance Checklist — #12 of the production readiness roadmap.

Every micro-live and live order MUST pass ALL checks before submission.
The checklist fails CLOSED: if any check cannot be verified (e.g. provider
unavailable), the result is FAIL, not PASS.

Usage:
    checklist = PreTradeChecklist(config=PreTradeChecklistConfig())
    result = await checklist.run(context)
    if not result.passed:
        log.error("pre_trade_blocked", failures=result.failing_checks)
        return  # do NOT submit the order

Each check is a standalone async function so individual checks can be tested
in isolation without constructing the full checklist.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any


class CheckId(StrEnum):
    MARKET_OPEN = "market_open"
    NO_BLACKOUT = "no_blackout"
    FRESH_MARKET_DATA = "fresh_market_data"
    FRESH_ORDER_BOOK = "fresh_order_book"
    RECONCILER_CLEAN = "reconciler_clean"
    KILL_SWITCH_OFF = "kill_switch_off"
    RISK_STATE_HEALTHY = "risk_state_healthy"
    STRATEGY_APPROVED = "strategy_approved"
    SYMBOL_TRADABLE = "symbol_tradable"
    ORDER_SIZE_VALID = "order_size_valid"
    CIRCUIT_BREAKERS_CLEAR = "circuit_breakers_clear"
    CAPITAL_POLICY_ALLOWS = "capital_policy_allows"
    LIVE_MODE_ENABLED = "live_mode_enabled"


@dataclass(frozen=True)
class CheckResult:
    check_id: CheckId
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class PreTradeChecklistResult:
    passed: bool
    checks: list[CheckResult]
    evaluated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def failing_checks(self) -> list[CheckId]:
        return [c.check_id for c in self.checks if not c.passed]

    @property
    def summary(self) -> str:
        if self.passed:
            return f"pre-trade OK ({len(self.checks)} checks passed)"
        fails = ", ".join(self.failing_checks)
        return f"pre-trade BLOCKED — {len(self.failing_checks)} failing: [{fails}]"


@dataclass
class PreTradeContext:
    """All inputs required to run the pre-trade checklist.

    Callers must populate every field. Leaving a field as None will cause the
    corresponding check to FAIL (fail-closed behaviour).
    """

    symbol: str
    strategy_id: str
    order_qty: Decimal
    order_notional: Decimal

    # From feature flags store
    kill_switch_active: bool | None = None

    # Market session state
    market_is_open: bool | None = None
    in_blackout_window: bool | None = None

    # Data freshness (seconds since last update — None means unknown)
    market_data_age_seconds: float | None = None
    order_book_age_ms: float | None = None

    # Sub-system health
    reconciler_is_clean: bool | None = None
    risk_state_healthy: bool | None = None
    circuit_breakers_clear: bool | None = None
    capital_policy_allows: bool | None = None

    # Strategy checks
    strategy_is_approved: bool | None = None
    strategy_expires_at: datetime | None = None

    # Symbol / order validity
    symbol_is_tradable: bool | None = None
    order_size_within_limits: bool | None = None

    # Live mode gate — must be True for any real order to proceed
    live_mode_enabled: bool | None = None


@dataclass
class PreTradeChecklistConfig:
    """Thresholds and toggles for individual checks."""

    max_market_data_age_seconds: float = 60.0
    max_order_book_age_ms: float = 500.0
    require_order_book: bool = True  # set False for paper trading only
    require_live_mode_flag: bool = True  # always True for live; False for paper tests


class PreTradeChecklist:
    """Runs all pre-trade compliance checks and returns a consolidated result.

    Fail-closed: if ANY check cannot be evaluated (value is None), it FAILS.
    """

    def __init__(self, config: PreTradeChecklistConfig | None = None) -> None:
        self._config = config or PreTradeChecklistConfig()

    async def run(self, ctx: PreTradeContext) -> PreTradeChecklistResult:
        checks = [
            self._check_kill_switch(ctx),
            self._check_live_mode(ctx),
            self._check_market_open(ctx),
            self._check_blackout(ctx),
            self._check_market_data(ctx),
            self._check_order_book(ctx),
            self._check_reconciler(ctx),
            self._check_risk_state(ctx),
            self._check_circuit_breakers(ctx),
            self._check_strategy_approved(ctx),
            self._check_symbol_tradable(ctx),
            self._check_order_size(ctx),
            self._check_capital_policy(ctx),
        ]
        all_passed = all(c.passed for c in checks)
        return PreTradeChecklistResult(passed=all_passed, checks=checks)

    def _check_kill_switch(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.kill_switch_active is None:
            return CheckResult(
                CheckId.KILL_SWITCH_OFF, False, "kill switch state unknown — fail closed"
            )
        if ctx.kill_switch_active:
            return CheckResult(CheckId.KILL_SWITCH_OFF, False, "kill switch is active")
        return CheckResult(CheckId.KILL_SWITCH_OFF, True)

    def _check_live_mode(self, ctx: PreTradeContext) -> CheckResult:
        if not self._config.require_live_mode_flag:
            return CheckResult(CheckId.LIVE_MODE_ENABLED, True, "live mode check skipped (paper)")
        if ctx.live_mode_enabled is None:
            return CheckResult(
                CheckId.LIVE_MODE_ENABLED, False, "live_trading_enabled flag unknown — fail closed"
            )
        if not ctx.live_mode_enabled:
            return CheckResult(
                CheckId.LIVE_MODE_ENABLED, False, "live_trading_enabled=false — orders disabled"
            )
        return CheckResult(CheckId.LIVE_MODE_ENABLED, True)

    def _check_market_open(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.market_is_open is None:
            return CheckResult(CheckId.MARKET_OPEN, False, "market session state unknown")
        if not ctx.market_is_open:
            return CheckResult(CheckId.MARKET_OPEN, False, "market is closed")
        return CheckResult(CheckId.MARKET_OPEN, True)

    def _check_blackout(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.in_blackout_window is None:
            return CheckResult(CheckId.NO_BLACKOUT, False, "blackout window state unknown")
        if ctx.in_blackout_window:
            return CheckResult(
                CheckId.NO_BLACKOUT, False, "system is in a blackout window — orders disabled"
            )
        return CheckResult(CheckId.NO_BLACKOUT, True)

    def _check_market_data(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.market_data_age_seconds is None:
            return CheckResult(CheckId.FRESH_MARKET_DATA, False, "market data age unknown")
        max_age = self._config.max_market_data_age_seconds
        if ctx.market_data_age_seconds > max_age:
            return CheckResult(
                CheckId.FRESH_MARKET_DATA,
                False,
                f"market data stale: age={ctx.market_data_age_seconds:.1f}s > max={max_age}s",
            )
        return CheckResult(CheckId.FRESH_MARKET_DATA, True)

    def _check_order_book(self, ctx: PreTradeContext) -> CheckResult:
        if not self._config.require_order_book:
            return CheckResult(CheckId.FRESH_ORDER_BOOK, True, "order book check skipped (paper)")
        if ctx.order_book_age_ms is None:
            return CheckResult(CheckId.FRESH_ORDER_BOOK, False, "order book unavailable")
        max_age = self._config.max_order_book_age_ms
        if ctx.order_book_age_ms > max_age:
            return CheckResult(
                CheckId.FRESH_ORDER_BOOK,
                False,
                f"order book stale: age={ctx.order_book_age_ms:.0f}ms > max={max_age:.0f}ms",
            )
        return CheckResult(CheckId.FRESH_ORDER_BOOK, True)

    def _check_reconciler(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.reconciler_is_clean is None:
            return CheckResult(CheckId.RECONCILER_CLEAN, False, "reconciler state unknown")
        if not ctx.reconciler_is_clean:
            return CheckResult(
                CheckId.RECONCILER_CLEAN,
                False,
                "reconciler reports unresolved mismatches — orders blocked",
            )
        return CheckResult(CheckId.RECONCILER_CLEAN, True)

    def _check_risk_state(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.risk_state_healthy is None:
            return CheckResult(CheckId.RISK_STATE_HEALTHY, False, "risk state unavailable")
        if not ctx.risk_state_healthy:
            return CheckResult(CheckId.RISK_STATE_HEALTHY, False, "risk state is unhealthy")
        return CheckResult(CheckId.RISK_STATE_HEALTHY, True)

    def _check_circuit_breakers(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.circuit_breakers_clear is None:
            return CheckResult(
                CheckId.CIRCUIT_BREAKERS_CLEAR, False, "circuit breaker state unknown"
            )
        if not ctx.circuit_breakers_clear:
            return CheckResult(
                CheckId.CIRCUIT_BREAKERS_CLEAR,
                False,
                "circuit breaker is tripped — trading halted",
            )
        return CheckResult(CheckId.CIRCUIT_BREAKERS_CLEAR, True)

    def _check_strategy_approved(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.strategy_is_approved is None:
            return CheckResult(CheckId.STRATEGY_APPROVED, False, "strategy approval unknown")
        if not ctx.strategy_is_approved:
            return CheckResult(
                CheckId.STRATEGY_APPROVED, False, f"strategy {ctx.strategy_id!r} not approved"
            )
        if ctx.strategy_expires_at is not None and datetime.now(UTC) > ctx.strategy_expires_at:
            return CheckResult(
                CheckId.STRATEGY_APPROVED,
                False,
                f"strategy approval expired at {ctx.strategy_expires_at.isoformat()}",
            )
        return CheckResult(CheckId.STRATEGY_APPROVED, True)

    def _check_symbol_tradable(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.symbol_is_tradable is None:
            return CheckResult(CheckId.SYMBOL_TRADABLE, False, "symbol tradability unknown")
        if not ctx.symbol_is_tradable:
            return CheckResult(
                CheckId.SYMBOL_TRADABLE, False, f"symbol {ctx.symbol!r} is not tradable"
            )
        return CheckResult(CheckId.SYMBOL_TRADABLE, True)

    def _check_order_size(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.order_size_within_limits is None:
            return CheckResult(CheckId.ORDER_SIZE_VALID, False, "order size limits unknown")
        if not ctx.order_size_within_limits:
            return CheckResult(
                CheckId.ORDER_SIZE_VALID,
                False,
                f"order qty={ctx.order_qty} or notional={ctx.order_notional} outside limits",
            )
        return CheckResult(CheckId.ORDER_SIZE_VALID, True)

    def _check_capital_policy(self, ctx: PreTradeContext) -> CheckResult:
        if ctx.capital_policy_allows is None:
            return CheckResult(CheckId.CAPITAL_POLICY_ALLOWS, False, "capital policy state unknown")
        if not ctx.capital_policy_allows:
            return CheckResult(
                CheckId.CAPITAL_POLICY_ALLOWS, False, "capital policy blocks this order"
            )
        return CheckResult(CheckId.CAPITAL_POLICY_ALLOWS, True)


def build_paper_context(
    symbol: str,
    strategy_id: str,
    order_qty: Decimal,
    order_notional: Decimal,
    **overrides: Any,
) -> PreTradeContext:
    """Build a pre-populated context suitable for paper trading checks.

    Paper trading skips live-mode and order-book requirements but still enforces
    kill switch, circuit breakers, reconciler, and risk state.
    """
    ctx = PreTradeContext(
        symbol=symbol,
        strategy_id=strategy_id,
        order_qty=order_qty,
        order_notional=order_notional,
        live_mode_enabled=False,  # never required for paper
        in_blackout_window=False,
        market_is_open=True,  # crypto never closes; equity: caller must set
    )
    for k, v in overrides.items():
        object.__setattr__(ctx, k, v)
    return ctx
