"""Capital allocation policy — strategy and asset-level governance layer.

Enforces hard limits on how much capital can be deployed per strategy,
per asset, per asset class, and on daily/weekly loss budgets.

The RiskEngine calls CapitalPolicyEngine.check() BEFORE approving any order.
Returning a non-approved CapitalPolicyDecision blocks the order immediately.

Allocation states per strategy:
    ACTIVE      — normal operation
    PAUSED      — no new entries (existing positions may remain)
    REDUCED_RISK — position size scaled to reduced_risk_size_pct
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from trading_bot.core.models import AssetClass, OrderRequest, OrderSide, PortfolioSnapshot
from trading_bot.observability.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StrategyAllocationState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    REDUCED_RISK = "reduced_risk"


# ---------------------------------------------------------------------------
# Policy configuration (loaded from settings)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StrategyPolicy:
    """Per-strategy capital limits."""

    strategy_id: str
    max_capital_pct: float  # fraction of total equity, e.g. 0.25 = 25%
    state: StrategyAllocationState = StrategyAllocationState.ACTIVE
    reduced_risk_size_pct: float = 0.50  # position size multiplier in REDUCED_RISK


@dataclass(frozen=True)
class AssetClassPolicy:
    """Per-asset-class capital limits."""

    asset_class: AssetClass
    max_capital_pct: float  # e.g. 0.60 = max 60% in crypto


@dataclass(frozen=True)
class CapitalPolicyConfig:
    """Full capital allocation policy configuration."""

    max_capital_per_strategy_pct: float = 0.30  # default per-strategy cap
    max_capital_per_asset_pct: float = 0.20  # default per-asset cap
    daily_loss_budget_pct: float = 0.03  # 3% of equity — daily loss floor
    weekly_loss_budget_pct: float = 0.07  # 7% of equity — weekly loss floor

    # Per-strategy overrides (keyed by strategy_id)
    strategy_policies: dict[str, StrategyPolicy] | None = None

    # Per-asset-class overrides (keyed by asset class value)
    asset_class_policies: dict[str, AssetClassPolicy] | None = None

    # Correlated exposure limit — max combined allocation to assets
    # that share a correlation tag (future: use correlation matrix)
    max_correlated_exposure_pct: float = 0.50

    def strategy_policy(self, strategy_id: str) -> StrategyPolicy:
        """Return the policy for a strategy, falling back to defaults."""
        if self.strategy_policies and strategy_id in self.strategy_policies:
            return self.strategy_policies[strategy_id]
        return StrategyPolicy(
            strategy_id=strategy_id,
            max_capital_pct=self.max_capital_per_strategy_pct,
        )

    def asset_class_policy(self, asset_class: AssetClass) -> AssetClassPolicy:
        key = str(asset_class)
        if self.asset_class_policies and key in self.asset_class_policies:
            return self.asset_class_policies[key]
        return AssetClassPolicy(
            asset_class=asset_class,
            max_capital_pct=self.max_capital_per_asset_pct,
        )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapitalPolicyDecision:
    approved: bool
    reason: str
    # Adjusted quantity after REDUCED_RISK scaling (None if not adjusted)
    adjusted_quantity: Decimal | None = None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CapitalPolicyEngine:
    """Evaluates an OrderRequest against the capital allocation policy.

    Stateless — reads snapshot on every call so operator changes take effect
    immediately without restart.
    """

    def __init__(self, config: CapitalPolicyConfig | None = None) -> None:
        self._config = config or CapitalPolicyConfig()
        self._strategy_states: dict[str, StrategyAllocationState] = {}

    def check(
        self,
        order: OrderRequest,
        snapshot: PortfolioSnapshot,
        asset_class: AssetClass,
        weekly_pnl_pct: float = 0.0,
        fill_price: Decimal | None = None,
    ) -> CapitalPolicyDecision:
        """Evaluate the order against all capital policies.

        Args:
            order: The order being evaluated.
            snapshot: Current portfolio state.
            asset_class: Asset class of the order's symbol.
            weekly_pnl_pct: Current week's PnL as a fraction of equity (negative = loss).
            fill_price: Actual fill/reference price to use for capital calculations.
                        Required for accurate exposure checks. If None, order is rejected.
        """
        if order.side != OrderSide.BUY:
            return CapitalPolicyDecision(True, "sell orders are not capital-limited")

        equity = snapshot.total_equity
        if equity <= 0:
            return CapitalPolicyDecision(False, "portfolio equity is zero or negative")

        config = self._config

        # ── Daily loss budget ────────────────────────────────────────────────
        daily_loss = abs(float(snapshot.daily_pnl)) / float(equity)
        if float(snapshot.daily_pnl) < 0 and daily_loss >= config.daily_loss_budget_pct:
            return CapitalPolicyDecision(
                False,
                f"daily loss budget exhausted: loss {daily_loss:.2%} "
                f">= limit {config.daily_loss_budget_pct:.2%}",
            )

        # ── Weekly loss budget ───────────────────────────────────────────────
        if weekly_pnl_pct < 0 and abs(weekly_pnl_pct) >= config.weekly_loss_budget_pct:
            return CapitalPolicyDecision(
                False,
                f"weekly loss budget exhausted: loss {abs(weekly_pnl_pct):.2%} "
                f">= limit {config.weekly_loss_budget_pct:.2%}",
            )

        # ── Require explicit fill price ──────────────────────────────────────
        if fill_price is None or fill_price <= Decimal("0"):
            return CapitalPolicyDecision(
                False,
                "fill_price is missing or invalid — cannot calculate capital exposure",
            )

        strategy_id = order.strategy_id or "__default__"
        policy = config.strategy_policy(strategy_id)

        # Runtime state overrides config state (operator may pause/resume at run time)
        runtime_state = self._strategy_states.get(strategy_id)
        effective_state = runtime_state if runtime_state is not None else policy.state

        # ── Strategy paused ──────────────────────────────────────────────────
        if effective_state == StrategyAllocationState.PAUSED:
            return CapitalPolicyDecision(
                False,
                f"strategy '{strategy_id}' is paused — no new entries allowed",
            )

        # ── Strategy capital cap ─────────────────────────────────────────────
        strategy_positions_value = sum(
            p.market_value for p in snapshot.positions if p.strategy_id == strategy_id
        )
        new_order_value = order.quantity * fill_price
        strategy_exposure = float((strategy_positions_value + new_order_value) / equity)

        effective_cap = policy.max_capital_pct
        if effective_state == StrategyAllocationState.REDUCED_RISK:
            effective_cap *= policy.reduced_risk_size_pct
            log.info(
                "capital_policy_reduced_risk_mode",
                strategy_id=strategy_id,
                effective_cap=effective_cap,
            )

        if strategy_exposure > effective_cap:
            return CapitalPolicyDecision(
                False,
                f"strategy '{strategy_id}' exposure {strategy_exposure:.2%} "
                f"would exceed cap {effective_cap:.2%}",
            )

        # ── Per-asset capital cap ────────────────────────────────────────────
        asset_positions_value = sum(
            p.market_value for p in snapshot.positions if p.symbol == order.symbol
        )
        asset_exposure = float((asset_positions_value + new_order_value) / equity)
        if asset_exposure > config.max_capital_per_asset_pct:
            cap = config.max_capital_per_asset_pct
            return CapitalPolicyDecision(
                False,
                f"asset '{order.symbol}' exposure {asset_exposure:.2%} would exceed cap {cap:.2%}",
            )

        # ── Asset-class capital cap ──────────────────────────────────────────
        ac_policy = config.asset_class_policy(asset_class)
        ac_positions_value = sum(
            p.market_value for p in snapshot.positions if p.asset_class == asset_class
        )
        ac_exposure = float((ac_positions_value + new_order_value) / equity)
        if ac_exposure > ac_policy.max_capital_pct:
            ac_cap = ac_policy.max_capital_pct
            return CapitalPolicyDecision(
                False,
                f"asset class '{asset_class}' exposure {ac_exposure:.2%} "
                f"would exceed cap {ac_cap:.2%}",
            )

        log.debug(
            "capital_policy_approved",
            strategy_id=strategy_id,
            symbol=order.symbol,
            strategy_exposure=f"{strategy_exposure:.2%}",
            asset_exposure=f"{asset_exposure:.2%}",
        )
        return CapitalPolicyDecision(True, "")

    def set_strategy_state(
        self,
        strategy_id: str,
        state: StrategyAllocationState,
    ) -> None:
        """Set the allocation state for a strategy.  Creates a default policy entry
        if one does not already exist.  Idempotent."""
        if strategy_id not in self._strategy_states:
            self._strategy_states[strategy_id] = StrategyAllocationState.ACTIVE
        self._strategy_states[strategy_id] = state
        log.info(
            "strategy_allocation_state_changed",
            strategy_id=strategy_id,
            new_state=state,
        )

    def get_strategy_state(self, strategy_id: str) -> StrategyAllocationState:
        return self._strategy_states.get(strategy_id, StrategyAllocationState.ACTIVE)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_capital_policy_engine: CapitalPolicyEngine | None = None


def get_capital_policy_engine() -> CapitalPolicyEngine:
    """Return the module-level CapitalPolicyEngine singleton."""
    global _capital_policy_engine
    if _capital_policy_engine is None:
        _capital_policy_engine = CapitalPolicyEngine()
    return _capital_policy_engine
