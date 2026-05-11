# trading-bot — Claude Code Instructions

## Project Overview

Professional-grade automated trading bot — Stage 0 Infrastructure.
Full specification in `trading_bot/docs/PLAN.md` (v5 approved).

Target assets: BTC/USDT (Binance), SPY/QQQ/SOXX ETFs (Alpaca).
Current stage: Stage 0 (Infrastructure & Engineering Standards).

## Architecture Principles

- Risk-first, infrastructure-first
- No strategy may bypass the risk engine
- Raw market data is write-once, immutable
- Every state-changing operation must be idempotent
- All timestamps are UTC-aware (naive datetimes are rejected at model boundaries)
- No print() in production code — structlog only
- Configuration changes require PR review

## Directory Guide

```
trading_bot/
├── config/         — YAML configs + pydantic-settings (secrets via env vars only)
├── core/           — Domain models, events, exceptions, contracts
│                     NO imports from other trading_bot packages
├── data/           — OHLCV ingestion, Parquet partitioner, Pandera validation
├── data_quality/   — Freshness watchdog, anomaly detection
├── database/       — asyncpg pool, Alembic migrations, audit log
├── exchange/       — ExchangeInterface implementations (Binance Stage 0, Alpaca Stage 5)
├── data_providers/ — DataProviderInterface implementations (yfinance, CCXT)
├── feature_flags/  — DB-backed flags with TTL cache + @feature_required decorator
├── idempotency/    — UUID v7 keys, Postgres store, @idempotent decorator
├── observability/  — structlog, OpenTelemetry, Prometheus metrics
├── scheduler/      — APScheduler jobs (daily OHLCV ingestion)
├── utils/          — time_sync, rate_limiter, signals (OS signal handling)
├── docs/
│   ├── adr/        — Architecture Decision Records (8 initial ADRs)
│   ├── runbooks/   — Incident response procedures
│   └── post_mortems/ — Blameless post-mortem archive
└── notebooks/      — Research ONLY — never imported by production
```

## Pre-Commit Checklist (ALWAYS before commit)

```bash
uv run ruff format .
uv run ruff check . --fix
uv run mypy trading_bot/ --ignore-missing-imports --no-strict-optional
uv run pytest tests/unit tests/property tests/replay -v
```

All must pass with zero errors.

## Commit Convention

Conventional Commits (enforced by commitizen):

```
feat(data): add OHLCV resumable downloader
fix(risk): correct drawdown percentage calculation
docs(adr): add ADR-0009 for order routing
test(property): add Hypothesis test for Kelly sizing
refactor(exchange): extract rate limiter to utils/
```

Breaking changes: append `!` after scope: `feat(core)!: rename OHLCVBar fields`

## Development Workflow

1. Work directly on `main` — no branch required
2. Pre-commit checks must pass before committing
3. Push directly: `git push origin main`
4. Sync before starting new work: `git fetch origin && git pull --ff-only origin main`

## Deployment Workflow (Railway)

After every successful coding session, the changes MUST be deployed to Railway.
Railway auto-deploys from the default branch (`main`) on every push.

Steps:
1. Commit changes on the development branch
2. Push the development branch to GitHub
3. Merge into `main` (via PR if `main` is protected, otherwise directly)
4. Pushing to `main` triggers Railway auto-deploy — no manual deploy needed

Config: `railway.toml` (Dockerfile builder, `alembic upgrade head` preDeploy,
`python -m trading_bot.main` start, `/readyz` healthcheck).

## Key Constraints

- **NO live trading until Stage 5** — `live_trading_enabled = false` always
- **NO order placement until Stage 5** — `place_order()` raises NotImplementedError
- **NEVER log API keys** — redact before passing to logger
- **NEVER commit .env** — it is in .gitignore
- **NEVER skip the promotion pipeline** — research → shadow → paper → micro-live → live
- **UTC everywhere** — naive datetimes are rejected at model validation

## Current Stage Status

- [x] Stage 0: Infrastructure & Engineering Standards
- [x] Stage 1: Data Engineering (BTC/USDT historical download)
- [x] Stage 2: Real-Time WebSocket Infrastructure
- [x] Stage 3: Strategy Engine (SMA, RSI)
- [x] Stage 4: Backtesting Framework
- [x] Stage 5: Execution Engine & Paper Trading
- [x] Stage 6: Safety Layer & Production Controls
- [x] Stage 7: Deployment & Infrastructure
- [x] Stage 8: Quant & AI Expansion

## When Adding New Code

1. If architectural decision: write ADR in `trading_bot/docs/adr/`
2. If operational: write runbook in `trading_bot/docs/runbooks/`
3. Property-based tests (Hypothesis) for risk engine, parsers, sizing
4. Feature flags for any new feature (`feature_flags.yaml` + DB seed)
5. Prometheus metrics for anything observable
6. Audit log entry for state-changing operations
7. CHANGELOG.md entry for user-visible changes

## GitHub Repo

https://github.com/Gkamashidze/trading-bot

Development branch: `claude/trading-bot-stage-zero-g85yF`
Main branch: `main` (protected — requires PR)
