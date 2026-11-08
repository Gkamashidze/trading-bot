# ADR-0010: Readiness requires verified evidence

Date: 2026-11-08. Status: accepted for paper operation; live remains disabled.

Fill-price changes are not strategy returns. Rejected submissions are not completed
trades, daily drawdown is not lifetime drawdown, and a balance query proves neither
trade permissions nor disabled withdrawal permissions. Missing data must not pass.

Record fee-inclusive strategy equity from actual fills and fresh market marks in
the existing portfolio evidence JSON. Keep legacy evidence immutable. Promotion
counts observed closed days and completed exits within the marked history. Missing
marks, unmatched inventory and evidence gaps block eligibility. Inventory belongs
to one strategy per symbol in the current portfolio model.

Require the standard 30-day/100-round-trip system minimum, comparable paper/backtest
metrics, a documented exchange permission audit, a clean fresh reconciliation and
current named operator approval. Blocking warnings and skipped criteria fail closed.
No code path may manufacture an approval or lower the minimums.

New audit records use schema 2.0 and hash the event envelope as well as the canonical
payload. A database transaction advisory lock serializes writers. Nullable append
sequence metadata orders new records without modifying old event content. Verification
checks both hashes and predecessor links. Historical violations are reported and
retained; they cannot be repaired by silently rewriting or deleting old records.

Operational effects: legacy Sharpe values no longer qualify a strategy, and new
marked evidence must accumulate. Migration 0009 is additive and compatible with the
previous application for rollback. Production dashboard routes require authentication;
health probes stay public. Dependency and source scans are blocking CI checks.

Portfolio risk uses fresh WebSocket marks and the day's equity high-water mark.
Gains are not drawdowns. Exact cash, day-start equity and the daily peak are
persisted in an atomic optional risk checkpoint beside the legacy snapshot JSON,
so previous releases can still read the base snapshot during rollback. Recovery
retains same-day baselines and tries an older valid snapshot if the newest pair
is damaged. Concurrent strategy order mutations are serialized in the paper runner.
