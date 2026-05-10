"""Pre-trade risk gate.

Checks every proposed OrderRequest against portfolio state and configured
risk limits. Returns a RiskDecision — never raises.

Circuit-breaker tiers (from base.yaml / RiskSettings):
  tier1_daily_drawdown_pct (5%)  → pause new positions
  tier2_daily_drawdown_pct (10%) → full halt
  tier3_daily_drawdown_pct (15%) → emergency (future: auto-liquidation)
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trading_bot.config import get_settings
from trading_bot.core.models import OrderRequest, OrderSide, PortfolioSnapshot
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    tier: int = 0  # 0 = OK, 1/2/3 = circuit-breaker tier


class RiskEngine:
    """Stateless pre-trade risk gate.

    Settings are read on each call so runtime changes (e.g. operator
    tightening limits) take effect immediately without a restart.
    """

    def pre_trade_check(
        self,
        order: OrderRequest,
        snapshot: PortfolioSnapshot,
        fill_price: Decimal,
    ) -> RiskDecision:
        risk = get_settings().risk
        equity = snapshot.total_equity

        if equity <= 0:
            return RiskDecision(False, "portfolio equity is zero or negative")

        # ── Daily drawdown circuit breakers ─────────────────────────────────
        dd_abs = abs(float(snapshot.daily_drawdown_pct))

        limit3 = risk.tier3_daily_drawdown_pct
        limit2 = risk.tier2_daily_drawdown_pct
        limit1 = risk.tier1_daily_drawdown_pct

        if dd_abs >= limit3:
            return RiskDecision(
                False, f"tier-3 emergency: drawdown {dd_abs:.1%} >= {limit3:.1%}", tier=3
            )
        if dd_abs >= limit2:
            return RiskDecision(
                False, f"tier-2 halt: drawdown {dd_abs:.1%} >= {limit2:.1%}", tier=2
            )
        if dd_abs >= limit1:
            return RiskDecision(
                False, f"tier-1 pause: drawdown {dd_abs:.1%} >= {limit1:.1%}", tier=1
            )

        # ── BUY-side checks only ─────────────────────────────────────────────
        if order.side == OrderSide.BUY:
            order_value = order.quantity * fill_price

            # Reserved cash floor
            cash_after = snapshot.cash_balance - order_value
            floor = equity * Decimal(str(risk.reserved_cash_floor_pct))
            if cash_after < floor:
                pct = risk.reserved_cash_floor_pct
                return RiskDecision(
                    False, f"order would breach reserved cash floor ({pct:.0%} of equity)"
                )

            # Max single-asset concentration
            existing = sum(p.market_value for p in snapshot.positions if p.symbol == order.symbol)
            concentration = float((existing + order_value) / equity)
            limit = risk.max_single_asset_pct
            if concentration > limit:
                return RiskDecision(
                    False,
                    f"{order.symbol} concentration {concentration:.1%} > limit {limit:.0%}",
                )

        log.debug("risk_approved", symbol=order.symbol, side=order.side)
        return RiskDecision(True, "")
