# trading-bot

Professional-grade automated trading system — Python 3.12, institutional-grade engineering.

**Current operation: paper trading and production-readiness validation.**

The main infrastructure, market-data, strategy, backtesting, execution and safety
modules are implemented. This does not certify live trading. Real-money execution
remains disabled until the evidence, permission, reconciliation and human review
requirements pass. Status reviewed: 2026-11-08.

---

## Architecture Principles

- Risk-first, infrastructure-first
- Deterministic, replayable, auditable
- No strategy may bypass the risk engine
- Safety > aggressiveness, reliability > complexity
- All timestamps UTC, all operations idempotent

Full specification: [`docs/PLAN.md`](docs/PLAN.md) (v5)

---

## Project Structure

```
trading_bot/
├── config/           — Hierarchical YAML config + pydantic-settings
├── core/             — Domain models, events, exceptions, contracts
├── data/             — OHLCV downloader (Parquet, partitioned, resumable)
├── data_quality/     — Freshness watchdog, anomaly detection
├── database/         — asyncpg pool, Alembic migrations, audit log
├── exchange/         — Exchange adapters (Binance Stage 0)
├── data_providers/   — Data providers (yfinance)
├── feature_flags/    — DB-backed feature flags with @feature_required
├── idempotency/      — UUID v7 keys + @idempotent decorator
├── observability/    — structlog, OpenTelemetry, Prometheus
├── scheduler/        — APScheduler daily ingestion jobs
├── utils/            — time_sync, rate_limiter, signals
├── docs/
│   ├── adr/          — Architecture Decision Records
│   ├── runbooks/     — Incident response procedures
│   └── post_mortems/ — Blameless post-mortem archive
└── notebooks/        — Research ONLY (never imported by production)
```

---

## Quick Start

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- PostgreSQL 16+

```bash
# Clone and install
git clone https://github.com/Gkamashidze/trading-bot.git
cd trading-bot
uv sync --extra dev

# Configure environment
cp .env.example .env   # then edit with your values

# Validate environment
uv run verify-env

# Run tests (no DB required)
uv run pytest tests/unit tests/property tests/replay -v
```

### With Database

```bash
export DATABASE_URL=postgresql+asyncpg://trading_bot:changeme@localhost:5432/trading_bot_dev
uv run alembic upgrade head
uv run python trading_bot/main.py
```

---

## Development

```bash
# Format + lint + typecheck + test
uv run ruff format . && uv run ruff check . --fix
uv run mypy trading_bot/ --ignore-missing-imports --no-strict-optional
uv run pytest tests/unit tests/property tests/replay -v

# Install pre-commit hooks
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

---

## Safety

`live_trading_enabled=false` and the global micro-live code gate remain disabled.
The automated crypto runner uses `PaperExchange`. The explicit micro-live operator
path requires its own readiness, risk and idempotency checks; do not use real
orders as tests or bypass promotion requirements.

Production dashboard access requires a separate, randomly generated
`DASHBOARD_API_KEY` of at least 32 characters. Browser username: `operator`;
password: the variable's value. API clients use `X-API-Key`, never query strings.
Health probes remain public. An unset production key fails closed.

- [Readiness report](trading_bot/go_live/criteria.py): at least 30 observed paper
  days and 100 completed round trips, verified parity and audit history, fresh
  clean reconciliation, documented exchange permissions and current human approval.
- [Rollback procedure](trading_bot/docs/runbooks/deployment-rollback.md)
- [Credential exposure procedure](trading_bot/docs/runbooks/credential-exposure.md)
- [Readiness architecture decision](trading_bot/docs/adr/ADR-0010-readiness-evidence-and-audit-integrity.md)

Legacy fill-price Sharpe estimates cannot approve a strategy. Marked equity
capture starts with the new recorder; older history is retained, and missing
historical marks are not fabricated. Strategy and system readiness are separate.

## Deployment and verification

Work on a development branch, run the full pre-commit checks, and open a PR into
protected `main`. Merge only after required checks pass and the user authorizes
release. Railway deploys `main` automatically and runs additive migrations first.
Never bypass branch protection or activate real trading as part of deployment.

CI blocks on dependency vulnerabilities, source security findings and newly
detected credentials. It also verifies migrations twice, database transaction
rollback and concurrent audit chain writes on disposable PostgreSQL.
