# trading-bot

Professional-grade automated trading system — Python 3.12, institutional-grade engineering.

**Current Stage: 0 — Infrastructure & Engineering Standards**

---

## Architecture Principles

- Risk-first, infrastructure-first
- Deterministic, replayable, auditable
- No strategy may bypass the risk engine
- Safety > aggressiveness, reliability > complexity
- All timestamps UTC, all operations idempotent

Full specification: [`trading_bot/docs/PLAN.md`](trading_bot/docs/PLAN.md) (v5)

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

`live_trading_enabled = false` — ALWAYS false in Stage 0. All exchange operations are read-only.
`place_order()` raises `NotImplementedError` until Stage 5.

---

## Roadmap

| Stage | Status | Description |
|-------|--------|-------------|
| 0 | ✅ In Progress | Infrastructure & Engineering Standards |
| 1 | ⏳ Next | Data Engineering & Historical OHLCV |
| 2 | ⏳ Planned | Real-Time WebSocket Infrastructure |
| 3 | ⏳ Planned | Strategy Engine |
| 4 | ⏳ Planned | Backtesting Framework |
| 5 | ⏳ Planned | Execution Engine & Paper Trading |
| 6 | ⏳ Planned | Safety Layer & Production Controls |
| 7 | ⏳ Planned | Deployment & Infrastructure |
| 8 | ⏳ Future | Quant & AI Expansion |
