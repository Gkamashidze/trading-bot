"""Fill model abstraction for backtesting and paper trading.

Three models are provided:

  PerfectFillModel  — legacy behavior (instant fill at signal price, no fees).
                      Use only for sanity-checking strategy logic.

  RealisticFillModel — production default. Simulates:
    - bid/ask spread (configurable bps)
    - maker/taker fees
    - market impact (volume-proportional slippage)
    - partial fills (probabilistic)
    - latency assumption (delay before fill)
    - stale quote rejection (price moved > staleness_threshold_pct)

FillResult separates gross PnL from net PnL so backtests can report
the true cost of trading alongside the raw strategy alpha.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum

# ---------------------------------------------------------------------------
# Enums / profiles
# ---------------------------------------------------------------------------


class FillModelProfile(StrEnum):
    IDEAL = "ideal"  # PerfectFillModel
    REALISTIC = "realistic"  # RealisticFillModel with default params
    PESSIMISTIC = "pessimistic"  # RealisticFillModel with conservative params


# ---------------------------------------------------------------------------
# FillResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FillResult:
    """Outcome of a simulated fill.

    gross_fill_price: price before any fees / market impact
    net_fill_price:   effective price after fees and slippage
    filled_quantity:  actual quantity filled (< requested on partial fills)
    fee_paid:         total fee in quote currency
    slippage_cost:    spread + market impact cost in quote currency
    is_partial:       True if only part of the order was filled
    rejected:         True if the order was rejected (stale quote or no liquidity)
    reject_reason:    human-readable rejection reason (empty if not rejected)
    latency_ms:       simulated order-to-fill latency
    """

    gross_fill_price: float
    net_fill_price: float
    filled_quantity: float
    fee_paid: float
    slippage_cost: float
    is_partial: bool = False
    rejected: bool = False
    reject_reason: str = ""
    latency_ms: float = 0.0

    @property
    def gross_value(self) -> float:
        return self.gross_fill_price * self.filled_quantity

    @property
    def net_value(self) -> float:
        return self.net_fill_price * self.filled_quantity

    @property
    def total_cost(self) -> float:
        """Total transaction cost (fees + slippage) in quote currency."""
        return self.fee_paid + self.slippage_cost


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class FillModel(ABC):
    """Abstract fill model.  All models must be deterministic given the same
    rng_seed so backtests are reproducible."""

    @abstractmethod
    def simulate_buy(
        self,
        reference_price: float,
        quantity: float,
        volume_at_price: float = 0.0,
        rng: random.Random | None = None,
    ) -> FillResult:
        """Simulate a BUY fill at `reference_price`."""

    @abstractmethod
    def simulate_sell(
        self,
        reference_price: float,
        quantity: float,
        volume_at_price: float = 0.0,
        rng: random.Random | None = None,
    ) -> FillResult:
        """Simulate a SELL fill at `reference_price`."""

    def compute_net_pnl(
        self,
        entry_result: FillResult,
        exit_result: FillResult,
    ) -> tuple[float, float]:
        """Return (gross_pnl, net_pnl) for a completed round-trip trade."""
        if entry_result.rejected or exit_result.rejected:
            return 0.0, 0.0

        gross_pnl = (
            exit_result.gross_fill_price - entry_result.gross_fill_price
        ) * entry_result.filled_quantity
        net_pnl = gross_pnl - entry_result.total_cost - exit_result.total_cost
        return gross_pnl, net_pnl


# ---------------------------------------------------------------------------
# PerfectFillModel
# ---------------------------------------------------------------------------


class PerfectFillModel(FillModel):
    """Fills immediately at reference_price with zero fees and zero slippage.

    Intended for debugging strategy logic only. Never use for performance
    evaluation — it systematically overstates returns.
    """

    def simulate_buy(
        self,
        reference_price: float,
        quantity: float,
        volume_at_price: float = 0.0,
        rng: random.Random | None = None,
    ) -> FillResult:
        return FillResult(
            gross_fill_price=reference_price,
            net_fill_price=reference_price,
            filled_quantity=quantity,
            fee_paid=0.0,
            slippage_cost=0.0,
        )

    def simulate_sell(
        self,
        reference_price: float,
        quantity: float,
        volume_at_price: float = 0.0,
        rng: random.Random | None = None,
    ) -> FillResult:
        return FillResult(
            gross_fill_price=reference_price,
            net_fill_price=reference_price,
            filled_quantity=quantity,
            fee_paid=0.0,
            slippage_cost=0.0,
        )


# ---------------------------------------------------------------------------
# RealisticFillModel
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RealisticFillConfig:
    """Configuration for RealisticFillModel."""

    # Bid/ask half-spread in basis points (1 bps = 0.01%)
    half_spread_bps: float = 5.0  # 5 bps each side → 10 bps total spread

    # Exchange fees
    taker_fee_rate: float = 0.001  # 0.10%
    maker_fee_rate: float = 0.0005  # 0.05%
    use_maker_fee: bool = False  # market orders pay taker fee

    # Market impact: slippage proportional to order size / available volume
    # impact_bps = market_impact_factor * (order_qty / volume_at_price) * 10_000
    market_impact_factor: float = 0.1

    # Partial fill simulation
    partial_fill_probability: float = 0.05  # 5% chance of partial fill
    partial_fill_min_pct: float = 0.70  # minimum 70% filled on partial

    # Latency
    mean_latency_ms: float = 50.0  # mean order-to-fill latency
    latency_std_ms: float = 20.0  # std dev

    # Stale quote rejection
    # Order is rejected if price has moved more than this % since signal
    staleness_threshold_pct: float = 0.005  # 0.5% price move = stale


REALISTIC_PROFILES: dict[FillModelProfile, RealisticFillConfig] = {
    FillModelProfile.IDEAL: RealisticFillConfig(
        half_spread_bps=0.0,
        taker_fee_rate=0.0,
        maker_fee_rate=0.0,
        market_impact_factor=0.0,
        partial_fill_probability=0.0,
        mean_latency_ms=0.0,
        latency_std_ms=0.0,
        staleness_threshold_pct=1.0,  # never stale in ideal mode
    ),
    FillModelProfile.REALISTIC: RealisticFillConfig(),  # defaults above
    FillModelProfile.PESSIMISTIC: RealisticFillConfig(
        half_spread_bps=15.0,
        taker_fee_rate=0.0015,
        maker_fee_rate=0.001,
        market_impact_factor=0.3,
        partial_fill_probability=0.15,
        partial_fill_min_pct=0.50,
        mean_latency_ms=150.0,
        latency_std_ms=50.0,
        staleness_threshold_pct=0.002,
    ),
}


class RealisticFillModel(FillModel):
    """Production-grade fill simulation.

    All randomness is seeded through the supplied rng so backtests are
    fully reproducible given the same random seed.
    """

    def __init__(self, config: RealisticFillConfig | None = None) -> None:
        self._cfg = config or RealisticFillConfig()

    @classmethod
    def from_profile(cls, profile: FillModelProfile) -> RealisticFillModel:
        return cls(REALISTIC_PROFILES[profile])

    def simulate_buy(
        self,
        reference_price: float,
        quantity: float,
        volume_at_price: float = 0.0,
        rng: random.Random | None = None,
    ) -> FillResult:
        return self._simulate(
            reference_price=reference_price,
            quantity=quantity,
            is_buy=True,
            volume_at_price=volume_at_price,
            rng=rng or random.Random(),  # noqa: S311
        )

    def simulate_sell(
        self,
        reference_price: float,
        quantity: float,
        volume_at_price: float = 0.0,
        rng: random.Random | None = None,
    ) -> FillResult:
        return self._simulate(
            reference_price=reference_price,
            quantity=quantity,
            is_buy=False,
            volume_at_price=volume_at_price,
            rng=rng or random.Random(),  # noqa: S311
        )

    def _simulate(
        self,
        reference_price: float,
        quantity: float,
        is_buy: bool,
        volume_at_price: float,
        rng: random.Random,
    ) -> FillResult:
        cfg = self._cfg

        # ── Latency ───────────────────────────────────────────────────────────
        latency_ms = max(0.0, rng.gauss(cfg.mean_latency_ms, cfg.latency_std_ms))

        # ── Stale quote check ─────────────────────────────────────────────────
        # Simulate microstructure noise proportional to execution latency.
        # drift_sigma grows with latency (≈0.001% per ms); at latency_ms=0 drift=0.
        drift_sigma = (latency_ms / 1_000.0) * 0.00001
        price_drift_pct = rng.gauss(0.0, drift_sigma) if drift_sigma > 0.0 else 0.0
        live_price = reference_price * (1 + price_drift_pct)
        abs_drift = abs(price_drift_pct)
        if abs_drift >= cfg.staleness_threshold_pct:
            return FillResult(
                gross_fill_price=reference_price,
                net_fill_price=reference_price,
                filled_quantity=0.0,
                fee_paid=0.0,
                slippage_cost=0.0,
                rejected=True,
                reject_reason=(
                    f"stale quote: price moved {abs_drift:.3%} "
                    f">= threshold {cfg.staleness_threshold_pct:.3%}"
                ),
                latency_ms=latency_ms,
            )

        # ── Spread ────────────────────────────────────────────────────────────
        half_spread = live_price * (cfg.half_spread_bps / 10_000)
        # Buyer pays ask (reference + half_spread); seller receives bid (reference - half_spread)
        gross_price = live_price + half_spread if is_buy else live_price - half_spread

        # ── Market impact ─────────────────────────────────────────────────────
        if volume_at_price > 0:
            impact_bps = cfg.market_impact_factor * (quantity / volume_at_price) * 10_000
        else:
            impact_bps = 0.0
        # Cap at 99% so fill price never reaches zero regardless of trade size
        impact_pct = min(impact_bps / 10_000, 0.99)
        impact_cost_per_unit = gross_price * impact_pct
        fill_price_before_fee = (
            gross_price + impact_cost_per_unit if is_buy else gross_price - impact_cost_per_unit
        )

        # ── Partial fill ──────────────────────────────────────────────────────
        if rng.random() < cfg.partial_fill_probability:
            fill_pct = rng.uniform(cfg.partial_fill_min_pct, 1.0)
            filled_qty = quantity * fill_pct
            is_partial = True
        else:
            filled_qty = quantity
            is_partial = False

        # ── Fee ───────────────────────────────────────────────────────────────
        fee_rate = cfg.maker_fee_rate if cfg.use_maker_fee else cfg.taker_fee_rate
        gross_value = fill_price_before_fee * filled_qty
        fee_paid = gross_value * fee_rate

        # Net fill price includes fee amortised per unit
        fee_per_unit = fee_paid / filled_qty if filled_qty > 0 else 0.0
        net_fill_price = (
            fill_price_before_fee + fee_per_unit if is_buy else fill_price_before_fee - fee_per_unit
        )

        slippage_cost = abs(fill_price_before_fee - reference_price) * filled_qty

        return FillResult(
            gross_fill_price=gross_price,
            net_fill_price=net_fill_price,
            filled_quantity=filled_qty,
            fee_paid=fee_paid,
            slippage_cost=slippage_cost,
            is_partial=is_partial,
            rejected=False,
            latency_ms=latency_ms,
        )
