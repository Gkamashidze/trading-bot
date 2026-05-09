"""Alembic migration environment.

Loads DATABASE_URL from environment variables (never from alembic.ini).
Supports both online (live DB) and offline (SQL script) migration modes.
Uses async engine (asyncpg) — matches production driver, no psycopg2 needed.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import Any

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Load DB URL from environment — NEVER from alembic.ini or YAML
database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. Set it before running alembic commands."
    )

# Normalise to asyncpg scheme — Railway may provide postgres:// or postgresql://
if database_url.startswith("postgres://"):
    database_url = "postgresql+asyncpg://" + database_url[len("postgres://"):]
elif database_url.startswith("postgresql://"):
    database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

config.set_main_option("sqlalchemy.url", database_url)

target_metadata = None  # We use raw SQL migrations, not SQLAlchemy models


def run_migrations_offline() -> None:
    """Generate SQL script without connecting to the DB."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Any) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
