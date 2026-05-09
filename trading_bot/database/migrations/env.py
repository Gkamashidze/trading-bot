"""Alembic migration environment.

Loads DATABASE_URL from environment variables (never from alembic.ini).
Supports both online (live DB) and offline (SQL script) migration modes.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config object — access to values in alembic.ini
config = context.config

# Set up logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Load DB URL from environment — NEVER from alembic.ini or YAML
database_url = os.environ.get("DATABASE_URL", "")
if not database_url:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Set it before running alembic commands."
    )

# asyncpg URL → synchronous URL for Alembic (Alembic uses sync SQLAlchemy)
sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
config.set_main_option("sqlalchemy.url", sync_url)

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


def run_migrations_online() -> None:
    """Apply migrations directly to the connected DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
