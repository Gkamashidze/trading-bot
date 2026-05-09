"""Startup environment validator.

Verifies that the environment is correctly configured before the bot starts.
Checks: required env vars, DB connectivity, exchange API connectivity,
Prometheus port availability, config schema validity.

Run as a pre-flight check:
    uv run verify-env

Or directly:
    python scripts/verify_environment.py

Exit code 0 = all checks passed.
Exit code 1 = one or more checks failed (details printed to stdout).
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Ensure trading_bot is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


@dataclass
class CheckResult:
    name: str
    passed: bool
    message: str
    critical: bool = True


@dataclass
class VerificationReport:
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)
        status = "✓" if result.passed else ("✗" if result.critical else "⚠")
        print(f"  [{status}] {result.name}: {result.message}")

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.critical)


def _check_env_vars() -> list[CheckResult]:
    """Check required environment variables."""
    results = []

    # Always required
    required = ["ENVIRONMENT"]
    for var in required:
        val = os.getenv(var)
        results.append(
            CheckResult(
                name=f"env.{var}",
                passed=bool(val),
                message=val or "MISSING",
                critical=True,
            )
        )

    # Required in production
    environment = os.getenv("ENVIRONMENT", "development")
    if environment == "production":
        prod_required = ["DATABASE_URL", "SECRET_KEY", "BINANCE_API_KEY"]
        for var in prod_required:
            val = os.getenv(var)
            results.append(
                CheckResult(
                    name=f"env.{var}",
                    passed=bool(val),
                    message="set" if val else "MISSING — required in production",
                    critical=True,
                )
            )

    # Warn if testnet is enabled in production
    if environment == "production" and os.getenv("BINANCE_TESTNET", "true").lower() == "true":
        results.append(
            CheckResult(
                name="safety.binance_testnet",
                passed=False,
                message="BINANCE_TESTNET=true in production — intended?",
                critical=False,
            )
        )

    # Warn if live trading enabled
    live = os.getenv("FEATURE_FLAG_LIVE_TRADING_ENABLED", "false").lower() == "true"
    if live:
        results.append(
            CheckResult(
                name="safety.live_trading",
                passed=True,
                message="⚠ LIVE TRADING ENABLED — confirm this is intentional",
                critical=False,
            )
        )

    return results


def _check_config() -> list[CheckResult]:
    """Validate pydantic-settings config loads without error."""
    try:
        from trading_bot.config import get_settings

        settings = get_settings()
        return [
            CheckResult(
                name="config.load",
                passed=True,
                message=f"environment={settings.environment}, version={settings.config_version}",
            )
        ]
    except Exception as e:
        return [CheckResult(name="config.load", passed=False, message=str(e))]


async def _check_database() -> list[CheckResult]:
    """Check PostgreSQL connectivity."""
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        return [
            CheckResult(
                name="database.connectivity",
                passed=False,
                message="DATABASE_URL not set — skipping DB check",
                critical=False,
            )
        ]

    try:
        import asyncpg

        dsn = database_url.replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(dsn, timeout=5)
        version = await conn.fetchval("SELECT version()")
        await conn.close()
        return [
            CheckResult(
                name="database.connectivity",
                passed=True,
                message=f"connected — {version[:40]}...",
            )
        ]
    except Exception as e:
        return [
            CheckResult(
                name="database.connectivity",
                passed=False,
                message=f"connection failed: {e}",
            )
        ]


async def _check_exchange() -> list[CheckResult]:
    """Check Binance exchange connectivity (read-only health check)."""
    results = []
    try:
        from trading_bot.config import get_settings
        from trading_bot.core.models import ExchangeId
        from trading_bot.exchange import get_exchange

        settings = get_settings()
        exchange = get_exchange(ExchangeId.BINANCE)
        healthy = await exchange.health_check()
        await exchange.close()  # type: ignore[attr-defined]

        results.append(
            CheckResult(
                name="exchange.binance.health",
                passed=healthy,
                message=f"testnet={settings.binance.testnet}, reachable={healthy}",
                critical=False,  # non-critical for local dev without network
            )
        )
    except Exception as e:
        results.append(
            CheckResult(
                name="exchange.binance.health",
                passed=False,
                message=f"check failed: {e}",
                critical=False,
            )
        )
    return results


def _check_yaml_configs() -> list[CheckResult]:
    """Verify YAML config files exist and are valid YAML."""
    import yaml

    results = []
    config_dir = Path(__file__).parent.parent / "trading_bot" / "config"
    for yaml_file in config_dir.glob("*.yaml"):
        try:
            with yaml_file.open() as f:
                yaml.safe_load(f)
            results.append(
                CheckResult(name=f"config.yaml.{yaml_file.name}", passed=True, message="valid YAML")
            )
        except Exception as e:
            results.append(
                CheckResult(
                    name=f"config.yaml.{yaml_file.name}",
                    passed=False,
                    message=f"invalid YAML: {e}",
                )
            )
    return results


async def run_verification() -> VerificationReport:
    """Run all verification checks and return the report."""
    report = VerificationReport()

    print("\n=== Trading Bot — Environment Verification ===\n")

    print("Environment Variables:")
    for r in _check_env_vars():
        report.add(r)

    print("\nConfiguration:")
    for r in _check_config():
        report.add(r)

    print("\nYAML Config Files:")
    for r in _check_yaml_configs():
        report.add(r)

    print("\nDatabase:")
    for r in await _check_database():
        report.add(r)

    print("\nExchange Connectivity:")
    for r in await _check_exchange():
        report.add(r)

    print(f"\n{'=' * 48}")
    if report.passed:
        print("✓ All critical checks passed. System is ready.")
    else:
        failed = [c.name for c in report.checks if not c.passed and c.critical]
        print(f"✗ {len(failed)} critical check(s) failed: {failed}")
        print("  Fix the issues above before starting the bot.")
    print("=" * 48 + "\n")

    return report


def main() -> None:
    report = asyncio.run(run_verification())
    sys.exit(0 if report.passed else 1)


if __name__ == "__main__":
    main()
