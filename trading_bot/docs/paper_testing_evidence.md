# Paper Testing Evidence Store

## Purpose

The Evidence Store provides durable, queryable evidence for every paper testing session.
Evidence persists across process restarts and is the authoritative record for the
micro-live readiness review.

Dashboard snapshots are volatile. Evidence records are permanent.

---

## What Evidence Is Collected

| Table | Cadence | Content |
|---|---|---|
| `evidence_sessions` | On startup | Session lifecycle — environment, config hash, symbols |
| `evidence_portfolio_snapshots` | Every 15 min | Cash, equity, daily PnL, drawdown, positions |
| `evidence_signal_snapshots` | After every signal refresh | Signal value, strength, indicators per strategy/symbol |
| `evidence_backtest_snapshots` | After every backtest run | Metrics, return, drawdown, Sharpe per strategy |
| `evidence_tca_records` | After every paper fill/rejection | Slippage, latency, outcome, quality score |
| `evidence_accounting_records` | After every paper fill | Fill price, fee, realized PnL per order |
| `evidence_reconciliation_reports` | After every reconciliation run | Severity, discrepancies, block status |
| `evidence_alert_incidents` | On alert fire/clear | Severity, source, title, acknowledgment |
| `evidence_daily_summaries` | Daily at 00:05 UTC | Daily roll-up of all above |
| `evidence_weekly_summaries` | Monday at 00:10 UTC | Weekly roll-up |

All writes are idempotent — safe to replay.
All timestamps are UTC-aware (naive datetimes rejected at the model layer).

---

## How to Interpret Daily Reports

A daily summary covers one calendar day (UTC).

Key fields:
- `pnl` / `pnl_pct` — realized + unrealized P&L delta for the day
- `max_drawdown_pct` — peak intraday drawdown from day-start equity
- `trade_count` — filled orders (excludes rejected)
- `rejected_order_count` — orders blocked by risk engine or reconciliation
- `partial_fill_count` — orders filled at less than requested quantity
- `reconciliation_critical_count` — critical reconciliation events (should be 0)
- `alert_count` — alerts fired (any severity)

Healthy pattern: `pnl_pct` positive, `max_drawdown_pct` < 5%, `rejected_order_count` low,
`reconciliation_critical_count` = 0 every day.

---

## How to Interpret Weekly Reports

A weekly summary covers Monday–Sunday (UTC).

Additional fields beyond daily:
- `parity_score` — optional: similarity between paper results and most recent backtest
  over the same period. Range 0–1. Higher = paper behaviour matches backtest model.
  **TODO**: computed by the promotion pipeline when enough data is available.
- `strategy_metrics` — JSONB blob with per-strategy trade counts (populated incrementally)
- `incidents` — JSONB list of notable incidents for operator review

Healthy pattern: consistent week-over-week equity growth, drawdown within risk limits,
no critical reconciliation events, parity score > 0.70.

---

## Micro-Live Readiness Criteria

The final 30-day report (`GET /evidence/final_report`) evaluates these criteria:

| Criterion | Default Threshold | Configurable |
|---|---|---|
| `minimum_days_observed` | ≥ 30 calendar days | `evidence.min_days` |
| `minimum_trade_count` | ≥ 20 trades total | `evidence.min_trades` |
| `zero_unresolved_critical_reconciliation` | = 0 | hardcoded |
| `zero_unresolved_critical_alerts` | = 0 | hardcoded |
| `max_drawdown_within_threshold` | ≤ 20% | `evidence.max_drawdown_pct` |
| `rejected_order_rate_within_threshold` | ≤ 10% | `evidence.max_rejected_rate` |
| `no_evidence_gap` | no gap > 25h between snapshots | `evidence.max_evidence_gap_hours` |
| `paper_backtest_parity_score` | ≥ 0.70 (when available) | `evidence.min_parity_score` |

### Important: 30 Days Alone Is Not Sufficient

Meeting the 30-day threshold is **necessary but not sufficient** for micro-live eligibility.

All of the following must also hold:
1. Zero unresolved critical reconciliation events — any single critical event blocks eligibility
2. Zero unresolved critical alerts — operator must acknowledge and clear all critical incidents
3. Trade count ≥ 20 — the strategy must have been active, not idle
4. No evidence gaps > 25 hours — continuous monitoring is required; gaps suggest downtime
5. Drawdown within threshold — risk characteristics must match expectations
6. Parity score acceptable — paper execution must resemble the backtested model

### Possible Recommendations

| Recommendation | Meaning |
|---|---|
| `continue_paper` | Minimum days not yet reached; keep running |
| `fix_issues` | All blocking criteria met but soft criteria failed; fix before review |
| `eligible_for_micro_live_review` | All criteria passed; submit to operator for sign-off |
| `reject_strategy` | Critical reconciliation or alert incidents; strategy not viable |

**Micro-live is NEVER automatically approved.** `eligible_for_micro_live_review` means the
operator may initiate the GoLiveGate process. The GoLiveGate still requires explicit
operator approval and rollback plan confirmation.

---

## Operator Checklist for Paper Testing Review

Before requesting micro-live sign-off, the operator must confirm:

- [ ] `GET /evidence/final_report` shows `eligible_for_micro_live_review`
- [ ] All daily summaries are present (no missing days)
- [ ] All critical reconciliation events have been reviewed and root-caused
- [ ] No unacknowledged critical alerts in `evidence_alert_incidents`
- [ ] Drawdown profile reviewed — worst-case day identified and explained
- [ ] Slippage baseline documented — paper fills at mid-price (zero slippage expected)
- [ ] Trade count is representative — strategy fired during varied market conditions
- [ ] Weekly summaries reviewed — equity curve is plausible
- [ ] Parity score reviewed — paper vs backtest behaviour is consistent
- [ ] GoLiveGate criteria reviewed independently (separate from evidence criteria)
- [ ] Rollback plan documented
- [ ] Risk manager sign-off obtained

---

## Dashboard Endpoints

| Endpoint | Auth | Description |
|---|---|---|
| `GET /evidence/session` | none | Current paper session |
| `GET /evidence/daily` | none | Daily summaries (last 90 days) |
| `GET /evidence/weekly` | none | Weekly summaries (last 26 weeks) |
| `GET /evidence/portfolio_snapshots` | none | Last 50 portfolio snapshots |
| `GET /evidence/reconciliation` | none | Last 50 reconciliation reports |
| `GET /evidence/report` | none | Session aggregate report |
| `GET /evidence/final_report` | none | 30-day readiness report with recommendation |
| `GET /evidence/export/json` | API key | Full session export as JSON |
| `GET /evidence/export/csv` | API key | Daily summaries as CSV download |

Export endpoints require `X-API-Key` header if `DASHBOARD_API_KEY` is set.

---

## Configuration

All thresholds are configurable in `config/base.yaml` under the `evidence` key,
or via environment variables with `EVIDENCE__` prefix.

```yaml
evidence:
  enabled: true
  min_days: 30
  min_trades: 20
  max_drawdown_pct: 0.20
  max_rejected_rate: 0.10
  min_parity_score: 0.70
  max_evidence_gap_hours: 25
  portfolio_snapshot_interval_minutes: 15
```

To disable evidence capture entirely: `evidence.enabled: false`.

---

## TODOs (documented intentionally)

- `parity_score` on `WeeklyEvidenceSummary` is nullable and currently not computed.
  It will be populated by the promotion pipeline once the parity scoring module is wired.
- `evidence_backtest_snapshots` are not yet written by the backtest runner.
  The runner needs a post-run hook to call `store.insert_backtest_snapshot()`.
- `evidence_accounting_records` are not yet written by the execution router.
  The router needs a post-fill hook to call `store.insert_accounting_record()`.
- `evidence_tca_records` are not yet written by the execution router.
  The router needs a post-fill hook to call `store.insert_tca_record()`.
- `evidence_alert_incidents` are not yet written by the alerting system.
  The Telegram alerter or SLO monitor needs to call `store.insert_alert_incident()`.
- Signal snapshot writes from `strategies/runner.py` are not yet wired.

Each TODO represents a write-side integration hook. The evidence store and tables
are ready; the integrations are additive one-liners in each producing module.
