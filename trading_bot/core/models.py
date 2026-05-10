"""Core domain models and DTOs (Data Transfer Objects).

All models use Pydantic v2. Timestamps are always timezone-aware UTC.
Naive datetimes are rejected at the model boundary to prevent an entire
class of timestamp-related bugs (see ADR-0007 for rationale).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class AssetClass(StrEnum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    ETF = "etf"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(StrEnum):
    PENDING = "pending"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class TimeInForce(StrEnum):
    GTC = "gtc"  # good-till-cancelled
    IOC = "ioc"  # immediate-or-cancel
    FOK = "fok"  # fill-or-kill
    DAY = "day"  # day order


class ExchangeId(StrEnum):
    BINANCE = "binance"
    ALPACA = "alpaca"
    COINBASE = "coinbase"


class PromotionStage(StrEnum):
    RESEARCH = "research"
    SHADOW = "shadow"
    PAPER = "paper"
    MICRO_LIVE = "micro_live"
    LIVE = "live"
    RETIRED = "retired"


# ---------------------------------------------------------------------------
# Base model config
# ---------------------------------------------------------------------------


class _BaseDTO(BaseModel):
    """Shared config for all DTOs: immutable, no extra fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", use_enum_values=True)


# ---------------------------------------------------------------------------
# Market Data DTOs
# ---------------------------------------------------------------------------


class OHLCVBar(BaseModel):
    """A single OHLCV candle.

    Timestamps must be UTC-aware. Prices and volumes use Decimal for exact
    arithmetic — convert to float only at the boundary of vectorised computation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    exchange: ExchangeId
    timeframe: str  # e.g. "1h", "1d"
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal
    trade_count: int | None = None

    # Lineage metadata — required for data quality tracking
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = ""
    schema_version: str = "1.0"

    @field_validator("open_time", "close_time", "fetched_at", mode="before")
    @classmethod
    def require_utc(cls, v: Any) -> datetime:
        """Reject naive datetimes — UTC enforcement at the model boundary."""
        if isinstance(v, datetime):
            if v.tzinfo is None:
                raise ValueError(
                    f"Naive datetime rejected: {v!r}. "
                    "All timestamps must be UTC-aware (use datetime.now(timezone.utc) "
                    "or pandas Timestamp with tz='UTC')."
                )
            return v.astimezone(UTC)
        raise ValueError(f"Expected datetime, got {type(v)}")

    @model_validator(mode="after")
    def validate_ohlcv_invariants(self) -> OHLCVBar:
        """Enforce physical OHLCV invariants."""
        if self.high < self.low:
            raise ValueError(f"high ({self.high}) < low ({self.low})")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"open {self.open} outside [low={self.low}, high={self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"close {self.close} outside [low={self.low}, high={self.high}]")
        if self.volume < 0:
            raise ValueError(f"volume must be non-negative, got {self.volume}")
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        return self


class Ticker(BaseModel):
    """Real-time best bid/ask snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    exchange: ExchangeId
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    timestamp: datetime

    @field_validator("timestamp", mode="before")
    @classmethod
    def require_utc(cls, v: Any) -> datetime:
        if isinstance(v, datetime) and v.tzinfo is None:
            raise ValueError("Naive datetime rejected in Ticker.timestamp")
        return cast(datetime, v)

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / 2


# ---------------------------------------------------------------------------
# Order DTOs
# ---------------------------------------------------------------------------


class OrderRequest(BaseModel):
    """A request to submit an order — not yet submitted to an exchange."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    client_order_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str
    exchange: ExchangeId
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    strategy_id: str = ""
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    idempotency_key: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @model_validator(mode="after")
    def validate_limit_order(self) -> OrderRequest:
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("LIMIT order requires limit_price")
        if self.order_type == OrderType.STOP and self.stop_price is None:
            raise ValueError("STOP order requires stop_price")
        if self.quantity <= 0:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        return self


class OrderState(BaseModel):
    """The lifecycle state of an order tracked by the OMS."""

    model_config = ConfigDict(frozen=False, extra="forbid")  # mutable for state transitions

    client_order_id: str
    exchange_order_id: str | None = None
    symbol: str
    exchange: ExchangeId
    side: OrderSide
    order_type: OrderType
    requested_quantity: Decimal
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    strategy_id: str = ""
    correlation_id: str = ""
    idempotency_key: str = ""
    reject_reason: str | None = None


# ---------------------------------------------------------------------------
# Portfolio / Position DTOs
# ---------------------------------------------------------------------------


class Position(BaseModel):
    """A current open position in the portfolio."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    exchange: ExchangeId
    asset_class: AssetClass
    quantity: Decimal  # positive = long, negative = short (future)
    average_cost: Decimal
    current_price: Decimal
    opened_at: datetime
    strategy_id: str = ""

    @property
    def market_value(self) -> Decimal:
        return self.quantity * self.current_price

    @property
    def unrealised_pnl(self) -> Decimal:
        return (self.current_price - self.average_cost) * self.quantity

    @property
    def unrealised_pnl_pct(self) -> Decimal:
        if self.average_cost == 0:
            return Decimal("0")
        return (self.current_price - self.average_cost) / self.average_cost


class PortfolioSnapshot(BaseModel):
    """Point-in-time snapshot of the entire portfolio state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    taken_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    cash_balance: Decimal
    positions: list[Position]
    total_equity: Decimal
    daily_pnl: Decimal
    daily_drawdown_pct: Decimal
    correlation_id: str = ""

    @model_validator(mode="after")
    def validate_drawdown(self) -> PortfolioSnapshot:
        if self.daily_drawdown_pct < -1:
            raise ValueError("daily_drawdown_pct cannot be below -100%")
        return self


# ---------------------------------------------------------------------------
# Signal DTO
# ---------------------------------------------------------------------------


class Signal(BaseModel):
    """A trading signal emitted by a strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    strategy_id: str
    strategy_version: str
    promotion_stage: PromotionStage
    symbol: str
    exchange: ExchangeId
    side: OrderSide
    strength: float = Field(ge=0.0, le=1.0)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    hypothesis: str = ""  # why this signal was emitted (audit trail)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    config_snapshot: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Data Lineage DTO
# ---------------------------------------------------------------------------


class DataLineage(BaseModel):
    """Lineage metadata attached to every processed dataset.

    All fields are optional-with-defaults so existing callers that pass only
    (source, fetched_at, row_count) continue to work without changes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str  # e.g. "binance.fetch_ohlcv"
    fetched_at: datetime
    processed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    validator_version: str = "1.0"
    schema_version: str = "1.0"
    row_count: int
    checksum: str = ""  # sha256 of raw bytes before processing
    quarantined: bool = False
    quarantine_reason: str | None = None

    # Extended provenance fields (Stage 8+)
    provider: str = ""  # e.g. "binance", "yfinance", "alpaca"
    exchange: str = ""  # e.g. "BINANCE", "NYSE"
    symbol: str = ""  # e.g. "BTC/USDT"
    timeframe: str = ""  # e.g. "1h", "1d"
    ingestion_job_id: str = ""  # UUID of the APScheduler job run
    storage_path: str = ""  # relative path inside data/raw/
    dataset_snapshot_id: str = ""  # immutable snapshot UUID (see data/lineage.py)


# ---------------------------------------------------------------------------
# Real-Time Price Tick DTO (Stage 2 — WebSocket feed)
# ---------------------------------------------------------------------------


class PriceTick(BaseModel):
    """One real-time price update from the Binance 24hr miniTicker WebSocket stream."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    price: Decimal
    open_24h: Decimal
    high_24h: Decimal
    low_24h: Decimal
    volume_24h: Decimal
    timestamp: datetime
    source: str = "binance_ws"

    @property
    def change_pct(self) -> float:
        """24h price change as a percentage (positive = up, negative = down)."""
        if self.open_24h == 0:
            return 0.0
        return float((self.price - self.open_24h) / self.open_24h * 100)
