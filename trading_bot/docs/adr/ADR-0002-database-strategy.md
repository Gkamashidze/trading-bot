# ADR-0002: Database Strategy — Postgres + DuckDB/Parquet (OLTP/OLAP Separation)

**Status:** Accepted
**Date:** 2024-01-01
**Deciders:** Architecture team

---

## Context

The system requires two fundamentally different data access patterns:

1. **OLTP (transactional):** orders, executions, audit log, idempotency keys,
   feature flags. Small rows, high write frequency, point lookups, ACID.

2. **OLAP (analytical):** OHLCV time-series, backtests, portfolio analytics.
   Large datasets, range scans, aggregations, vectorized reads.

Mixing these workloads in a single Postgres instance causes I/O contention:
OLAP queries scan large tables and evict OLTP data from shared_buffers,
causing cache thrashing and elevated latency on transactional paths.

---

## Decision

**OLTP: PostgreSQL 16+ (with TimescaleDB extension)**

- Orders, executions, feature flags, idempotency keys, audit log
- TimescaleDB hypertables for time-series data (if needed in OLTP)
- asyncpg connection pool, raw SQL, no ORM
- Alembic for schema management

**OLAP: Parquet files + DuckDB**

- OHLCV bars stored as Parquet partitioned by (exchange/symbol/timeframe/YYYY-MM)
- DuckDB used for in-process analytical queries (GROUP BY, window functions)
- No separate OLAP server needed — DuckDB is embedded
- Cold storage: S3/R2 for long-term archival (Stage 7+)

---

## Consequences

### Positive

- OLAP queries never contend with OLTP writes
- Parquet files are immutable (write-once, audit-friendly)
- DuckDB vectorized scans are 10-100× faster than Postgres for aggregations
- Parquet is the industry standard for backtesting data

### Negative

- Data lives in two places — lineage tracking is required
- Cross-system joins require ETL (acceptable for batch analytics)
- TimescaleDB adds extension dependency to Postgres

### Risks

- Parquet files on disk can be lost — require S3 backup in Stage 7
- DuckDB is embedded: if the process crashes during a write, WAL may need repair

---

## Alternatives Considered

| Option | Reason Rejected |
|--------|-----------------|
| Postgres only | OLAP query contention, no columnar storage, slow for large scans |
| ClickHouse | Separate server, heavy ops, overkill for Stage 0-5 |
| InfluxDB | Narrow query model, poor joins, vendor lock-in |
| SQLite | No concurrent writes, not production-grade |

---

## References

- DuckDB: https://duckdb.org/
- TimescaleDB: https://www.timescale.com/
- Parquet columnar format: https://parquet.apache.org/
