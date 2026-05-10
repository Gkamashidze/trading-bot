"""Backtesting configuration — fee model, capital, slippage."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from trading_bot.backtesting.fill_model import FillModelProfile


class BacktestConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    initial_capital: float = Field(default=10_000.0, gt=0)
    fee_rate: float = Field(default=0.001, ge=0.0, le=0.1)
    slippage_rate: float = Field(default=0.0005, ge=0.0, le=0.05)
    position_size_pct: float = Field(default=1.0, gt=0.0, le=1.0)
    annual_trading_days: int = Field(default=365)

    # Fill model controls
    fill_model_profile: FillModelProfile = FillModelProfile.REALISTIC
    # Deterministic seed for fill model RNG (None = random each run)
    fill_rng_seed: int | None = None
