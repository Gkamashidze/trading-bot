"""Domain exception hierarchy.

All exceptions carry a runbook_url so alert messages can link operators
directly to the relevant incident response procedure.
"""

from __future__ import annotations


class TradingBotError(Exception):
    """Base exception for all trading-bot errors."""

    runbook_url: str = (
        "https://github.com/Gkamashidze/trading-bot/tree/main/trading_bot/docs/runbooks"
    )

    def __init__(self, message: str, runbook_url: str | None = None) -> None:
        super().__init__(message)
        if runbook_url:
            self.runbook_url = runbook_url


# ── Configuration ─────────────────────────────────────────────────────────────


class ConfigurationError(TradingBotError):
    """Invalid or missing configuration."""


class SecretMissingError(ConfigurationError):
    """A required secret environment variable is absent."""


# ── Data ──────────────────────────────────────────────────────────────────────


class DataError(TradingBotError):
    """Base for all data-layer errors."""


class DataFetchError(DataError):
    """Failed to fetch data from a remote source."""


class DataValidationError(DataError):
    """DataFrame schema validation failed (Pandera)."""


class DataStalenessError(DataError):
    """Data is stale beyond the configured freshness threshold."""


class DataAnomalyError(DataError):
    """Anomalous tick detected (z-score breach, negative price, zero volume)."""


# ── Exchange ──────────────────────────────────────────────────────────────────


class ExchangeError(TradingBotError):
    """Base for all exchange communication errors."""

    runbook_url = "https://github.com/Gkamashidze/trading-bot/tree/main/trading_bot/docs/runbooks/exchange-api-outage.md"


class ExchangeConnectionError(ExchangeError):
    """Cannot reach exchange API."""


class ExchangeAuthError(ExchangeError):
    """API key authentication / permission failure."""


class ExchangeRateLimitError(ExchangeError):
    """Exchange rate limit hit."""

    def __init__(self, message: str, retry_after_seconds: float = 60.0) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class ExchangeBannedError(ExchangeError):
    """Exchange has banned our IP. Wait until banned_until_ms before retrying."""

    def __init__(self, message: str, banned_until_ms: int) -> None:
        super().__init__(message)
        self.banned_until_ms = banned_until_ms


class ExchangeOrderError(ExchangeError):
    """Order submission / management failed."""


class ExchangeReconciliationError(ExchangeError):
    """OMS state diverged from exchange state."""

    runbook_url = "https://github.com/Gkamashidze/trading-bot/tree/main/trading_bot/docs/runbooks/reconciliation-mismatch.md"


# ── Risk ──────────────────────────────────────────────────────────────────────


class RiskError(TradingBotError):
    """Base for risk engine errors."""

    runbook_url = "https://github.com/Gkamashidze/trading-bot/tree/main/trading_bot/docs/runbooks/risk-breach.md"


class DrawdownBreachError(RiskError):
    """Daily drawdown circuit breaker triggered."""

    def __init__(self, message: str, tier: int, drawdown_pct: float) -> None:
        super().__init__(message)
        self.tier = tier
        self.drawdown_pct = drawdown_pct


class RiskVetoError(RiskError):
    """Risk engine vetoed a proposed order."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


# ── Execution ─────────────────────────────────────────────────────────────────


class ExecutionError(TradingBotError):
    """Base for order execution errors."""


class OrderRejectedError(ExecutionError):
    """Exchange rejected the order (fixable or unfixable)."""

    def __init__(self, message: str, fixable: bool = False) -> None:
        super().__init__(message)
        self.fixable = fixable


class OrderTimeoutError(ExecutionError):
    """Order was not filled within the allowed timeout."""


class IdempotencyCollisionError(ExecutionError):
    """An idempotency key collision was detected — possible duplicate submission."""


# ── Feature Flags ─────────────────────────────────────────────────────────────


class FeatureDisabledError(TradingBotError):
    """Operation blocked because its feature flag is disabled."""

    def __init__(self, flag_name: str) -> None:
        super().__init__(f"Feature '{flag_name}' is disabled.")
        self.flag_name = flag_name


# ── Kill Switch ───────────────────────────────────────────────────────────────


class KillSwitchError(TradingBotError):
    """System-level kill switch activated — all trading halted."""

    runbook_url = "https://github.com/Gkamashidze/trading-bot/tree/main/trading_bot/docs/runbooks/kill-switch-activated.md"


# ── Time ─────────────────────────────────────────────────────────────────────


class ClockDriftError(TradingBotError):
    """Local clock drifted beyond acceptable threshold versus exchange time."""

    runbook_url = "https://github.com/Gkamashidze/trading-bot/tree/main/trading_bot/docs/runbooks/clock-drift.md"

    def __init__(self, message: str, drift_ms: float) -> None:
        super().__init__(message)
        self.drift_ms = drift_ms


# ── Database ──────────────────────────────────────────────────────────────────


class DatabaseError(TradingBotError):
    """Base for database-layer errors."""


class MigrationError(DatabaseError):
    """Database schema migration failed."""
