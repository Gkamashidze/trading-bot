"""Abstract contracts (interfaces) for all major subsystems.

Concrete implementations live in their respective sub-packages.
This file defines the contracts only — no implementation, no imports
from sub-packages. The goal is to make dependency boundaries explicit
and enable test doubles (mocks/stubs) without importing real dependencies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from typing import Any


class ExchangeInterface(ABC):
    """Abstract contract for all exchange adapters."""

    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch OHLCV bars. Returns raw exchange dicts (not yet validated DTOs)."""

    @abstractmethod
    async def place_order(self, order: Any) -> dict[str, Any]:
        """Submit an order. Returns raw exchange response."""

    @abstractmethod
    async def cancel_order(self, exchange_order_id: str, symbol: str) -> dict[str, Any]:
        """Cancel an open order."""

    @abstractmethod
    async def fetch_balances(self) -> dict[str, Decimal]:
        """Return current asset balances as {asset: amount}."""

    @abstractmethod
    async def get_server_time(self) -> datetime:
        """Return current exchange server time (UTC-aware)."""

    @abstractmethod
    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        """Return all open orders, optionally filtered by symbol."""

    @abstractmethod
    async def fetch_trade_fees(self, symbol: str) -> dict[str, Decimal]:
        """Return maker/taker fee rates for a symbol."""

    @abstractmethod
    async def get_symbol_info(self, symbol: str) -> dict[str, Any]:
        """Return symbol constraints: min order size, tick size, lot size."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if exchange is reachable and authenticated."""


class DataProviderInterface(ABC):
    """Abstract contract for historical market data providers."""

    @abstractmethod
    async def get_market_data(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Return OHLCV data for the given symbol and time range."""

    @abstractmethod
    async def get_corporate_actions(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
    ) -> list[dict[str, Any]]:
        """Return dividends and splits (splits, dividends, etc.)."""

    @abstractmethod
    async def get_market_calendar(self, exchange: str, year: int) -> list[dict[str, Any]]:
        """Return trading days, holidays, and half-days for a given year."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if provider is reachable."""


class AuditLogInterface(ABC):
    """Append-only, hash-chained audit log."""

    @abstractmethod
    async def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        correlation_id: str = "",
        actor: str = "system",
        occurred_at: datetime | None = None,
        config_snapshot: dict[str, Any] | None = None,
    ) -> str:
        """Append an event to the audit log. Returns the event hash."""

    @abstractmethod
    async def get_chain_head(self) -> str | None:
        """Return the hash of the most recently appended event."""

    @abstractmethod
    async def verify_chain(self, since_event_id: str | None = None) -> bool:
        """Verify the hash chain integrity. Returns True if intact."""


class FeatureFlagStoreInterface(ABC):
    """Runtime feature flag store backed by a persistent store."""

    @abstractmethod
    async def is_enabled(self, flag_name: str) -> bool:
        """Return current flag value. Falls back to YAML default if not in DB."""

    @abstractmethod
    async def set_flag(self, flag_name: str, value: bool, changed_by: str, reason: str) -> None:
        """Persist a flag change. Emits FlagChangeEvent on the event bus."""

    @abstractmethod
    async def refresh(self) -> None:
        """Reload flags from DB into the in-memory cache."""


class IdempotencyStoreInterface(ABC):
    """Stores idempotency keys to prevent duplicate state-changing operations."""

    @abstractmethod
    async def acquire(self, key: str, ttl_seconds: int = 604800) -> bool:
        """Attempt to acquire an idempotency key.

        Returns True if acquired (first time seen within TTL).
        Returns False if key already exists — operation is a duplicate.
        """

    @abstractmethod
    async def release(self, key: str) -> None:
        """Explicitly release a key (e.g. on confirmed failure)."""


class EventBusInterface(ABC):
    """Centralized event bus."""

    @abstractmethod
    async def publish(self, event: Any) -> None:
        """Publish an event to all subscribers."""

    @abstractmethod
    async def subscribe(self, event_type: str) -> AsyncIterator[Any]:
        """Async iterator that yields events of the given type."""


class RiskEngineInterface(ABC):
    """Independent risk engine — no strategy may bypass this."""

    @abstractmethod
    async def evaluate(self, signal: Any, portfolio: Any) -> tuple[bool, str]:
        """Evaluate a signal against current portfolio and risk rules.

        Returns (accepted, reason). Every decision is logged to the audit trail.
        """
