# Runbook: Chaos Drill Plan

**Runbook ID:** RB-0003
**Severity:** Planned exercise (not an incident response)
**Last Tested:** _TBD — required before micro-live promotion_
**Owner:** Operator
**Related Gate:** ROADMAP_LIVE.md Gate 0 — *"Chaos drill completed: at least one planned failure injection in staging"*

---

## Purpose

A chaos drill is a **controlled, planned failure injection** into a staging
environment to confirm the system degrades gracefully and recovers correctly.
The point is to verify behavior, not to break things in production.

Required outcomes per ROADMAP_LIVE.md:

1. The system survives the failure without manual intervention.
2. Operator alerts fire within the documented time budget.
3. Recovery is automatic where the runbook claims it is.
4. The post-mortem produces at least one improvement (monitoring, runbook,
   or code).

---

## Hard Rules

- **Never** run a chaos drill against production.
- **Never** drill on a day when the operator cannot watch for ≥2 hours afterwards.
- **Always** notify all stakeholders 24 hours in advance with the start time
  and the failure being injected.
- **Always** have the rollback procedure typed and ready before starting.
- **Always** record the drill in the audit log:
  ```sql
  INSERT INTO audit_log (event_type, actor, payload, occurred_at)
  VALUES ('chaos_drill_started', 'operator', '{"scenario": "...", "drill_id": "..."}', NOW());
  ```

---

## Drill Catalog

Each drill below is a complete, runnable scenario. Start with the lowest-risk
one and work up only after each prior drill passes.

### Drill 1 — DB Connection Loss (lowest risk)

**Scenario:** Postgres becomes unreachable for 60 seconds.

**Injection:**
- Staging: pause the Postgres service in Railway for 60s, then resume.
- Or block port 5432 with a firewall rule for 60s.

**Expected behavior:**
- Within 30s: `database_unreachable` alert in Telegram (WARNING level).
- WebSocket continues to deliver prices (cache stays warm).
- Strategy signals continue to compute (Parquet read path is independent of DB).
- New order placements are **rejected** because `paper_orders` writes fail.
- No process crash. `/readyz` returns 503; `/healthz` continues to return 200.

**After Postgres recovers:**
- Within 30s: `database_recovered` log entry (info level).
- `/readyz` returns 200.
- Connection pool reconnects without restart.
- No data loss in Parquet partitions or in evidence snapshots.

**Pass criteria:**
- [ ] Alert fired within 30s of outage start.
- [ ] No unhandled exceptions in logs other than the expected connection errors.
- [ ] `/readyz` flipped to 503 and back to 200 without operator action.
- [ ] Pool size returned to nominal (min_size connections active).

**Rollback if it goes wrong:**
- Resume the Postgres service immediately.
- If pool refuses to reconnect: restart the Railway service.

---

### Drill 2 — WebSocket Disconnect (medium risk)

**Scenario:** Binance WebSocket connection drops for 90 seconds.

**Injection:**
- Block outbound TCP to `stream.binance.com:9443` at the staging host.
- Or temporarily set `BINANCE_WS_URL=wss://invalid.example` and SIGHUP.

**Expected behavior:**
- Within 30s: `websocket_disconnect` alert.
- Reconnect attempts visible in logs (exponential backoff).
- Price cache continues to serve last-known ticks (with stale `timestamp`).
- Strategy refresh job logs `data_stale` warning when bar age > threshold.
- No new orders placed because freshness gate trips.

**After connection restores:**
- Reconnect succeeds within 30s of network restoration.
- Fresh ticks flow to cache.
- Strategy refresh resumes producing signals.

**Pass criteria:**
- [ ] Reconnect attempted within 15s of disconnect.
- [ ] Backoff is bounded (≤ 60s between attempts).
- [ ] No duplicate WS clients spawned (memory leak check).
- [ ] No spurious `paper_order_placed` events during the outage.

---

### Drill 3 — Stale Data Feed (medium risk)

**Scenario:** WebSocket stays connected but the last tick is artificially aged
to 5 minutes old.

**Injection:**
- In staging: insert a stale tick into the price cache:
  ```python
  cache = get_price_cache()
  stale = PriceTick(..., timestamp=datetime.now(UTC) - timedelta(minutes=5))
  await cache.update(stale)
  ```
- Suspend the real WebSocket task during the drill.

**Expected behavior:**
- Freshness watchdog (`data_quality/freshness.py`) detects stale data.
- Strategy refresh logs `signal_skipped` with reason `stale_data`.
- No orders placed.
- Dashboard "ცოცხ. ფასი" badge stays yellow.
- Telegram alert: `data_freshness_breach` (WARNING).

**Pass criteria:**
- [ ] Alert fires before any order is placed against stale data.
- [ ] Strategy gate blocks order placement explicitly (not coincidentally).
- [ ] Recovery is automatic once fresh ticks resume.

---

### Drill 4 — Circuit Breaker Trip (medium-high risk)

**Scenario:** Force `daily_drawdown_pct` past tier-1 threshold (default 2%).

**Injection:**
- In staging, manipulate `daily_drawdown_pct` in the portfolio manager
  directly, or simulate a series of large losing paper trades.
- Trigger `circuit_breaker_monitor_job` manually:
  ```python
  await get_circuit_breaker().check()
  ```

**Expected behavior:**
- Within 5 min: tier flips 0 → 1 (or higher).
- Telegram alert with current tier + drawdown %.
- New orders rejected with reason `circuit_breaker_tripped`.
- Position-sizing reduced if tier-1, halted if tier-2+.
- Daily reset at UTC 00:00 clears tier back to 0.

**Pass criteria:**
- [ ] Tier change reflected in dashboard Safety card within one poll cycle (30s).
- [ ] Order rejection logged with the correct reason.
- [ ] Tier persisted to DB snapshot (survives restart).
- [ ] `daily_portfolio_reset_job` at midnight UTC clears state.

---

### Drill 5 — Kill Switch Latency Under Load (highest risk)

**Scenario:** While the bot is actively placing paper orders, the operator
activates the kill switch and times the halt.

**Injection:**
- Run during a period of active signal generation (use historical replay if
  needed to produce many signals).
- Operator fires `/kill` while orders are mid-flight.

**Expected behavior:**
- All orders in flight at the moment of `/kill` are either completed or rolled
  back cleanly (no half-state).
- No new orders begin after the kill switch transitions to active.
- Halt visible in dashboard within 60s (already validated in
  `kill-switch-test.md`).

**Pass criteria:**
- [ ] Reuses the criteria from `kill-switch-test.md` Step 4.
- [ ] No order is left in `status='pending'` after the halt.
- [ ] Audit log captures the activation and the last completed order.

---

## Schedule

Recommended drill cadence before micro-live:

| Drill | Earliest Date | Required? |
|-------|---------------|-----------|
| 1 — DB connection loss | T-21 days from micro-live | Yes |
| 2 — WebSocket disconnect | T-14 days | Yes |
| 3 — Stale data feed | T-10 days | Yes |
| 4 — Circuit breaker trip | T-7 days | Yes |
| 5 — Kill switch under load | T-3 days | Yes |

All five must pass before flipping any asset's `status` to `micro_live_candidate`.

---

## Post-Drill Procedure

After every drill, **regardless of outcome:**

1. Mark drill end in audit log:
   ```sql
   INSERT INTO audit_log (event_type, actor, payload, occurred_at)
   VALUES ('chaos_drill_completed', 'operator',
           '{"drill_id": "...", "outcome": "pass|fail", "issues": []}', NOW());
   ```
2. Write a 1-page post-mortem in `trading_bot/docs/post_mortems/`:
   - What we expected
   - What actually happened
   - At least one improvement (monitoring, runbook update, code change)
3. File improvements as GitHub issues with the `chaos-drill` label.
4. Re-run any failed drill after the fix lands.

---

## Related

- ROADMAP_LIVE.md Gate 0
- `trading_bot/docs/runbooks/kill-switch-test.md`
- `trading_bot/docs/runbooks/websocket-disconnect.md`
- `trading_bot/safety/circuit_breaker.py`
- `trading_bot/data_quality/freshness.py`
