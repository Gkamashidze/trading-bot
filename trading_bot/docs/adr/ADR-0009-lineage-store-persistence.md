# ADR-0009: Lineage Store Persistence Strategy

**Status:** Proposed
**Date:** 2026-05-11
**Deciders:** Trading bot engineering
**Supersedes:** —

---

## Context

`LineageStore` (`trading_bot/data/lineage.py`) is the registry that ties every
`BacktestResult` to the exact `DataLineage` snapshot it was run against —
the audit trail required by the data-lineage enforcement rule.

The current implementation is **process-local and in-memory only**:

```python
_store: LineageStore = LineageStore()  # module-level dict
```

Consequences observed in production (Stage 8):

1. On every Railway redeploy / restart the snapshot dict is wiped.
2. `run_backtests()` previously raised `LineageError` for any symbol without
   a snapshot, causing the fire-and-forget `initial_backtest` task to fail
   silently and the dashboard to report "no data" indefinitely.
3. Even after the immediate fix (auto-registering snapshots from Parquet
   metadata — see "Interim Mitigation" below), snapshot IDs are not stable
   across processes, so cross-run provenance comparisons are unreliable.

## Interim Mitigation (shipped 2026-05-11)

- Backfill (`dashboard/app.py:_run_backfill`) registers a `DataLineage`
  snapshot after a successful download.
- `run_backtests()` auto-registers a snapshot from the loaded bars when no
  explicit snapshot exists for the symbol.

These changes make the system functional on the in-memory store, but the
underlying persistence gap remains.

---

## Decision

**Promote `LineageStore` to a PostgreSQL-backed implementation when any of the
following triggers fire:**

- A backtest result must be reproducible across deployments (e.g. results
  surfaced in audit reports or shared with reviewers).
- Stage 5 (live trading) begins — every live decision must trace back to a
  snapshot that survives process restarts.
- Multiple processes (scheduler + dashboard + future workers) need to share
  the same snapshot namespace.

The migration plan when triggered:

1. Add `dataset_snapshots` table (Alembic migration):
   - `snapshot_id TEXT PRIMARY KEY` (sha256, deterministic — keep existing
     `_snapshot_id` function so IDs stay stable across the migration)
   - `lineage JSONB NOT NULL` (serialized `DataLineage`)
   - `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
   - Index on `(lineage->>'symbol', created_at DESC)` for
     `_resolve_snapshot_id` lookups.
2. Replace the in-memory dict in `LineageStore` with asyncpg-backed
   read/write methods. Keep the public API (`create_snapshot`,
   `get_snapshot`, `verify_snapshot`, `all_snapshots`) unchanged.
3. Add an LRU cache (~1000 entries) in front of the DB for hot reads.
4. Backfill the table on first deploy by running
   `_auto_register_snapshot` against all symbols present in `data/raw/`.

---

## Consequences

### Positive

- Snapshot IDs survive restarts and deploys.
- Audit reports can cite a `snapshot_id` that any future process can
  resolve back to the originating `DataLineage`.
- Enables the "live decision → snapshot → backtest" trace required for
  Stage 5 compliance.

### Negative

- One additional table to maintain (migration, backup, retention).
- `create_snapshot` becomes async-only or requires a sync DB connection.
  Callers in synchronous code paths (`engine.run`) will need adjustment.

### Risks

- **Snapshot ID drift** if `_snapshot_id` formula changes after persisted
  rows exist. *Mitigation:* version the formula and store the version in
  the row; never silently change inputs to the hash.
- **Hot loop write amplification** if backfill creates many snapshots per
  run. *Mitigation:* `create_snapshot` is already idempotent — the DB
  `ON CONFLICT (snapshot_id) DO NOTHING` clause makes it a no-op on
  duplicates.

---

## Alternatives Considered

| Option | Reason Rejected (for now) |
|--------|---------------------------|
| Keep in-memory + auto-register on read | Current state. Works for the dashboard but provides no real provenance — every restart invents new IDs from current Parquet metadata. |
| File-backed JSON store (`data/lineage/*.json`) | Simpler than DB but requires its own locking, atomic-write, and cleanup story; we already run Postgres. |
| Object storage (S3) for snapshot blobs | Overkill for ~kilobyte rows; introduces new infra. |

---

## References

- `trading_bot/data/lineage.py` — current in-memory implementation
- `trading_bot/backtesting/runner.py` — `_auto_register_snapshot` (interim)
- `trading_bot/dashboard/app.py` — backfill snapshot registration (interim)
- ADR-0002 — Database strategy (asyncpg + Alembic)
