# ── Stage 1: build dependencies ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy lockfile + project manifest + alembic config first (layer cache)
COPY pyproject.toml uv.lock alembic.ini ./

# Install production deps only (no dev extras)
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Non-root user (security: containers should not run as root)
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Pre-create the data directory so Railway Volume mounts with correct ownership
RUN mkdir -p /data/raw && chown -R appuser:appgroup /data

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source + alembic config
COPY trading_bot/ ./trading_bot/
COPY --from=builder /app/alembic.ini ./

# Activate venv; PYTHONPATH ensures trading_bot is importable from /app
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check endpoint served by the dashboard (added in Step 3)
EXPOSE 8000

USER appuser

CMD ["python", "-m", "trading_bot.main"]
