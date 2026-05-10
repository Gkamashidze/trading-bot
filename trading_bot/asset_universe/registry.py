"""Asset universe registry.

Single source of truth for all assets the bot knows about. An asset must be
listed here before data ingestion, paper testing, or live trading can occur.

Status lifecycle (one-way promotion):
    disabled → research → paper → micro_live_candidate → live_candidate

Promotion gates:
    research → paper:               requires required_history_days of clean OHLCV
    paper → micro_live_candidate:   requires paper_min_days + paper_min_trades of evidence
    micro_live_candidate → live_candidate: human operator sign-off in audit log

live_trading_enabled = false is enforced globally at the bot level regardless
of any individual asset's status here.
"""

from __future__ import annotations

import functools
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from trading_bot.core.models import AssetClass, ExchangeId

_REGISTRY_YAML = Path(__file__).parent.parent / "config" / "asset_universe.yaml"

_MAX_CAPITAL_PCT_HARD_LIMIT = 0.50


class AssetStatus(StrEnum):
    DISABLED = "disabled"
    RESEARCH = "research"
    PAPER = "paper"
    MICRO_LIVE_CANDIDATE = "micro_live_candidate"
    LIVE_CANDIDATE = "live_candidate"


_TRADEABLE_STATUSES = frozenset(
    {AssetStatus.PAPER, AssetStatus.MICRO_LIVE_CANDIDATE, AssetStatus.LIVE_CANDIDATE}
)


class AssetSpec(BaseModel):
    """Full specification of one tradeable or candidate asset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    venue: ExchangeId
    asset_class: AssetClass
    status: AssetStatus
    phase: int = Field(ge=1, le=5)

    # Capital risk caps
    max_capital_pct: float = Field(gt=0.0, le=1.0)
    max_order_notional_usd: float = Field(gt=0.0)

    # Liquidity gates (checked before paper activation)
    min_24h_volume_usd: float = Field(ge=0.0)
    max_spread_bps: float = Field(ge=0.0)

    # History required before paper activation
    required_history_days: int = Field(ge=1)

    # Minimum evidence before micro-live review
    paper_min_days: int = Field(ge=1, default=30)
    paper_min_trades: int = Field(ge=0, default=20)

    # Allowed strategy IDs (empty = all current strategies are allowed)
    enabled_strategies: list[str] = Field(default_factory=list)

    # Feature flag that gates activation of this asset group
    feature_flag: str = ""

    # Documentation
    rationale: str = ""
    risks: str = ""

    # Experimental assets are excluded from the default paper universe
    experimental: bool = False

    @model_validator(mode="after")
    def _enforce_capital_hard_limit(self) -> AssetSpec:
        if self.max_capital_pct > _MAX_CAPITAL_PCT_HARD_LIMIT:
            raise ValueError(
                f"{self.symbol}: max_capital_pct {self.max_capital_pct:.0%} exceeds "
                f"hard limit of {_MAX_CAPITAL_PCT_HARD_LIMIT:.0%}. "
                "No single asset may dominate the portfolio."
            )
        return self


class AssetUniverseRegistry(BaseModel):
    """Immutable registry of all known assets."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assets: list[AssetSpec]

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def get(self, symbol: str) -> AssetSpec | None:
        for asset in self.assets:
            if asset.symbol == symbol:
                return asset
        return None

    def is_tradeable(self, symbol: str) -> bool:
        """True when the asset exists and its status permits paper trading."""
        spec = self.get(symbol)
        return spec is not None and spec.status in _TRADEABLE_STATUSES

    def is_data_eligible(self, symbol: str) -> bool:
        """True when data ingestion is allowed (research status or above)."""
        spec = self.get(symbol)
        return spec is not None and spec.status != AssetStatus.DISABLED

    # ------------------------------------------------------------------
    # Filtered views
    # ------------------------------------------------------------------

    def by_status(self, status: AssetStatus) -> list[AssetSpec]:
        return [a for a in self.assets if a.status == status]

    def by_phase(self, phase: int) -> list[AssetSpec]:
        return [a for a in self.assets if a.phase == phase]

    def tradeable(self) -> list[AssetSpec]:
        return [a for a in self.assets if a.status in _TRADEABLE_STATUSES]

    def research_and_above(self) -> list[AssetSpec]:
        """Assets where data ingestion is permitted (research status or higher)."""
        return [a for a in self.assets if a.status != AssetStatus.DISABLED]

    def crypto_symbols(self, tradeable_only: bool = False) -> list[str]:
        pool = self.tradeable() if tradeable_only else self.research_and_above()
        return [a.symbol for a in pool if a.asset_class == AssetClass.CRYPTO]

    def etf_symbols(self, tradeable_only: bool = False) -> list[str]:
        pool = self.tradeable() if tradeable_only else self.research_and_above()
        return [a.symbol for a in pool if a.asset_class in {AssetClass.ETF, AssetClass.EQUITY}]

    def all_symbols(self, tradeable_only: bool = False) -> set[str]:
        pool = self.tradeable() if tradeable_only else self.research_and_above()
        return {a.symbol for a in pool}


# ------------------------------------------------------------------
# Module-level singleton
# ------------------------------------------------------------------


def _load_registry() -> AssetUniverseRegistry:
    raw: dict[str, Any] = {}
    if _REGISTRY_YAML.exists():
        with _REGISTRY_YAML.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    assets = [AssetSpec(**entry) for entry in raw.get("assets", [])]
    return AssetUniverseRegistry(assets=assets)


@functools.lru_cache(maxsize=1)
def get_asset_registry() -> AssetUniverseRegistry:
    """Return the singleton registry (cached after first load)."""
    return _load_registry()
