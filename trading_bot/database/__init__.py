"""Database layer — asyncpg connection pool and repository base classes.

OLTP (Postgres): orders, executions, audit log, idempotency keys, feature flags.
OLAP (DuckDB / Parquet): OHLCV bars, backtests, analytics.

Raw SQL only — no ORM. All queries use parameterized placeholders ($1, $2, ...).
"""
