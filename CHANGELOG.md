# Changelog

All notable changes to trading-bot are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html)

---

## [Unreleased]

## [0.1.0] — 2024-01-01

### Added — Stage 0: Infrastructure & Engineering Standards

**Project Structure**
- Full modular directory structure per v5 architectural specification
- `trading_bot/core/`: domain models, events, exceptions, contracts
- `trading_bot/config/`: hierarchical YAML + pydantic-settings config system
- `trading_bot/observability/`: structlog, OpenTelemetry tracing, Prometheus metrics
- `trading_bot/exchange/`: ExchangeInterface + BinanceExchange adapter (read-only)
- `trading_bot/data_providers/`: DataProviderInterface + yfinance provider
- `trading_bot/idempotency/`: UUID v7 key generation, Postgres store, @idempotent decorator
- `trading_bot/feature_flags/`: DB-backed flags with TTL cache, @feature_required decorator
- `trading_bot/database/`: asyncpg pool, PostgresAuditLog (hash-chained, append-only)
- `trading_bot/data/`: OHLCVDownloader (partitioned, resumable, idempotent) + Pandera validation
- `trading_bot/data_quality/`: freshness watchdog, z-score anomaly detection
- `trading_bot/scheduler/`: APScheduler with Postgres job store + daily ingestion jobs
- `trading_bot/utils/`: time_sync (UTC enforcement, clock drift), rate_limiter (token bucket), signals (SIGTERM)
- `scripts/verify_environment.py`: startup environment validation

**Database**
- Alembic migration framework with environment-based DATABASE_URL loading
- Initial schema: audit_log, feature_flags, idempotency_keys, ohlcv_metadata
- audit_log: append-only, SHA-256 hash-chained (tamper detection)

**Testing**
- pytest + pytest-asyncio + Hypothesis (property-based testing)
- Unit tests: core models, Pandera validation, SMA indicator
- Property-based tests: Kelly criterion, drawdown bounds, OHLCV invariants, SMA bounds
- Replay test fixtures: JSON event stream format with expected outcomes

**Documentation**
- 8 Architecture Decision Records (ADR-0001 through ADR-0008)
- Runbook template + RB-0001: websocket-disconnect.md
- Post-mortem template (blameless format)
- CLAUDE.md: repo-specific instructions for Claude Code

**CI/CD**
- `.github/workflows/ci.yml`: lint, typecheck, tests, config-lint, security, migrations
- `.pre-commit-config.yaml`: ruff-format, ruff-lint, mypy, detect-secrets, large-file guard
- detect-secrets baseline (empty — no known false positives)

**Security**
- .env.example template (no secrets, API key rotation reminder)
- .gitignore: prevents .env, Parquet files, logs, secrets from being committed
- API key segregation documented: read-only / trade-only / withdraw-enabled
- detect-secrets pre-commit hook configured

---

[Unreleased]: https://github.com/Gkamashidze/trading-bot/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Gkamashidze/trading-bot/releases/tag/v0.1.0
