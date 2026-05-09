"""APScheduler job definitions for automated data ingestion.

Job store: Postgres (SQLAlchemyJobStore) — survives process restarts.
Failed jobs: exponential backoff via Tenacity + Telegram alert after N failures.
"""
