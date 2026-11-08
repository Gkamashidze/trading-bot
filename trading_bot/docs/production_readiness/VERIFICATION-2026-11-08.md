# Readiness and security verification — 2026-11-08

Scope: the Python application, configuration, dashboard, evidence, paper execution,
risk-state recovery, database migrations, audit integrity and deployment lifecycle.
Real-money trading remains disabled. No real-money order was used as a test.

## Verified before merge

| Check | Result |
| --- | --- |
| Python | 3.12.13, matching the production/CI minor version |
| Ruff format and lint | Passed |
| mypy | Passed, 165 application source files |
| Required unit/property/replay tests | 1033 passed, including schedule/readiness freshness compatibility |
| Coverage of configured unit-test scope | 74.63%, above the 50% required threshold |
| PostgreSQL integration tests | 8 passed on an isolated PostgreSQL 18 database |
| Chaos/contract test selection | 16 passed |
| Credentialed Alpaca paper execution tests | 7 skipped; no broker orders were sent |
| Dependency vulnerability audit | No known vulnerabilities in the pinned third-party set |
| Bandit medium/high findings | 0; container ingress bindings are documented exceptions |
| Newly detected credentials | 0; the checked-in false-positive baseline is unchanged |
| YAML configuration and workflow parse | Passed |
| Migration cycle | Upgrade, repeated upgrade, downgrade to base, re-upgrade and repeated upgrade passed |
| Full application startup | Database, scheduler, HTTP server and telemetry started |
| Local HTTP smoke checks | Health, evidence report, go-live report and promotion page returned 200 |
| Graceful shutdown | One SIGTERM stopped the corrected application and closed scheduler/database resources |

The database tests cover concurrent audit writers, canonical JSON hashes, tampered
metadata and fork detection, transactional rollback, idempotent flag changes,
persistent risk-state restoration, a complete paper buy/sell cycle, exact fee
accounting, inventory ownership and restart deduplication. Operator approvals are
also tested for one persisted result and one audit event per idempotency key.

## Changes with operational impact

- Production dashboard, report and export routes now require authentication.
  `DASHBOARD_API_KEY` must contain at least 32 characters. Browser username:
  `operator`. Keys in query strings are not accepted. Health probes stay public.
- Live trading cannot be enabled by a dashboard toggle. Real-money execution also
  remains behind the existing global code gate, readiness, persistent risk state,
  risk-engine and idempotency controls.
- Old fill-price Sharpe estimates and rejected submissions no longer qualify a
  strategy. New observations include actual fees and marked open inventory.
  Missing marks, historical inventory mismatches and evidence gaps are explicit
  blockers. No historical price, trade, equity mark or approval was fabricated.
- Legacy audit events are preserved. New schema-2.0 entries include event metadata
  in the hash and use serialized append ordering. Verification checks predecessor
  links and reports historical violations instead of overwriting them.
- A background read-only verification runs after production startup. Its
  `deployment_verification_complete` event records endpoint health and go-live
  blockers without exposing dashboard credentials. This is an infrastructure
  check, not permission to trade.

## Remaining requirements before real money

1. Revoke the previously exposed Telegram credential and replace it after log
   redaction is deployed. Confirm successful polling without credential leakage.
2. Accumulate the real minimum evidence: 30 observed marked days, the system's
   100 completed round trips, and the candidate strategy's own quality gates.
   Existing unmarked history cannot stand in for missing observations.
3. Validate paper/backtest parity for the same candidate, asset scope and period.
   Baseline SMA/RSI results do not demonstrate a profitable trading edge.
4. Investigate any historical audit violation reported by the deployed gate.
   Historical events must not be silently rewritten or the criterion bypassed.
5. Audit the intended live API key's permissions and restrictions, rehearse
   venue-specific reconciliation, rollback and position closing, then obtain a
   current named risk review and explicit operator approval.

These requirements remain blocking. Passing engineering tests, deploying main,
or the mere passage of calendar time does not satisfy them. This record does not
claim a credentialed broker execution test or an external penetration test.
