"""Type-safe hierarchical settings via pydantic-settings + YAML.

Merge order (later wins):
  base.yaml → {ENVIRONMENT}.yaml → environment variables

Call get_settings() once at startup; the result is cached (lru_cache).
The config snapshot (as dict) is available via settings.snapshot() for
attaching to audit log events and ensuring replay correctness.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root — used to resolve YAML paths
_CONFIG_DIR = Path(__file__).parent


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge `override` on top of `base`."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _build_yaml_defaults() -> dict[str, Any]:
    """Load and merge YAML config files; result becomes pydantic field defaults."""
    environment = os.getenv("ENVIRONMENT", "development")
    base = _load_yaml(_CONFIG_DIR / "base.yaml")
    env_specific = _load_yaml(_CONFIG_DIR / f"{environment}.yaml")
    merged = _deep_merge(base, env_specific)
    return merged


# ---------------------------------------------------------------------------
# Nested config models
# ---------------------------------------------------------------------------


class LoggingSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "console"] = "json"
    include_caller: bool = False


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    url: str = Field(default="", alias="DATABASE_URL")
    pool_min: int = 5
    pool_max: int = 20
    command_timeout: int = 30


class OtelSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    service_name: str = "trading-bot"
    exporter: Literal["console", "otlp"] = "console"
    otlp_endpoint: str = Field(default="", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    traces_sampler: str = "always_on"
    order_sample_rate: float = 1.0
    data_fetch_sample_rate: float = 0.1


class PrometheusSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    port: int = 9090
    path: str = "/metrics"
    enabled: bool = True


class RiskSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    tier1_daily_drawdown_pct: float = 0.05
    tier2_daily_drawdown_pct: float = 0.10
    tier3_daily_drawdown_pct: float = 0.15
    max_portfolio_leverage: float = 1.0
    reserved_cash_floor_pct: float = 0.10
    max_single_asset_pct: float = 0.30
    max_single_exchange_pct: float = 0.50
    kelly_fraction: float = 0.25
    volatility_target_annual: float = 0.15


class TimeSyncSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    warn_drift_ms: int = 100
    alert_drift_ms: int = 250
    halt_drift_ms: int = 500
    check_interval_seconds: int = 60


class LatencyBudgetsSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    data_ingestion_ms: int = 50
    signal_generation_ms: int = 100
    risk_check_ms: int = 20
    order_submission_ms: int = 200
    signal_to_fill_p99_ms: int = 500


class BinanceExchangeSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    api_key: str = Field(default="", alias="BINANCE_API_KEY")
    api_secret: str = Field(default="", alias="BINANCE_API_SECRET")
    testnet: bool = Field(default=True, alias="BINANCE_TESTNET")
    base_url: str = "https://api.binance.com"
    testnet_url: str = "https://testnet.binance.vision"
    timeout_seconds: int = 10
    retry_attempts: int = 4
    retry_backoff_base: int = 2


class TelegramSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    alert_chat_id: str = Field(default="", alias="TELEGRAM_ALERT_CHAT_ID")


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    """Root configuration object.

    Populated from merged YAML files + environment variables.
    Env vars override YAML values (pydantic-settings convention).
    """

    model_config = SettingsConfigDict(
        extra="ignore",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    # Top-level scalars
    environment: Literal["development", "staging", "production"] = "development"
    secret_key: str = Field(default="", alias="SECRET_KEY")
    config_version: str = "1.0.0"

    # Nested sub-configs — populated from YAML defaults + env overrides
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    otel: OtelSettings = Field(default_factory=OtelSettings)
    prometheus: PrometheusSettings = Field(default_factory=PrometheusSettings)
    risk: RiskSettings = Field(default_factory=RiskSettings)
    time_sync: TimeSyncSettings = Field(default_factory=TimeSyncSettings)
    latency_budgets: LatencyBudgetsSettings = Field(default_factory=LatencyBudgetsSettings)
    binance: BinanceExchangeSettings = Field(default_factory=BinanceExchangeSettings)
    telegram: TelegramSettings = Field(default_factory=TelegramSettings)

    @field_validator("environment", mode="before")
    @classmethod
    def normalise_environment(cls, v: str) -> str:
        return str(v).lower()

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Settings:
        """In production, critical secrets must be explicitly set."""
        if self.environment == "production":
            missing = []
            if not self.secret_key:
                missing.append("SECRET_KEY")
            if not self.database.url:
                missing.append("DATABASE_URL")
            if missing:
                raise ValueError(
                    f"Production environment missing required secrets: {missing}. "
                    "Inject via environment variables — never in YAML."
                )
        return self

    def snapshot(self) -> dict[str, Any]:
        """Return a config snapshot safe to attach to audit log events.

        Secrets are redacted. This snapshot is stored with every event to
        ensure deterministic replay even if config changes between events.
        """
        raw = self.model_dump()
        # Redact secret fields
        _redact_keys = {"secret_key", "api_key", "api_secret", "bot_token", "url"}

        def _redact(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {
                    k: "[REDACTED]" if k in _redact_keys else _redact(v) for k, v in obj.items()
                }
            return obj

        return cast(dict[str, Any], _redact(raw))

    def effective_binance_url(self) -> str:
        """Returns the correct Binance URL based on testnet setting."""
        return self.binance.testnet_url if self.binance.testnet else self.binance.base_url


def _load_settings() -> Settings:
    """Build Settings from merged YAML + env vars.

    Called once at module import via get_settings(). The YAML merge result
    is used as model defaults so env vars can override any field.
    """
    yaml_defaults = _build_yaml_defaults()

    # Flatten nested YAML dicts into pydantic-compatible kwargs
    # Pydantic-settings reads nested models from env via __ separator.
    # For YAML-sourced defaults we instantiate nested models directly.
    nested_overrides: dict[str, Any] = {}

    for key in ("logging", "database", "otel", "prometheus", "risk", "time_sync"):
        if key in yaml_defaults:
            nested_overrides[key] = yaml_defaults[key]

    if "latency_budgets_ms" in yaml_defaults:
        lb = yaml_defaults["latency_budgets_ms"]
        nested_overrides["latency_budgets"] = {
            f"{k}_ms" if not k.endswith("_ms") else k: v for k, v in lb.items()
        }

    if "exchange" in yaml_defaults and "binance" in yaml_defaults["exchange"]:
        nested_overrides["binance"] = yaml_defaults["exchange"]["binance"]

    # Build nested sub-settings from YAML first, then env vars will override
    return Settings(**nested_overrides)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance (cached after first call)."""
    return _load_settings()
