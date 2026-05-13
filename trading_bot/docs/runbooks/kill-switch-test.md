# Runbook: Kill Switch Test

**Runbook ID:** RB-0002
**Severity:** Test procedure (not an incident response)
**Last Tested:** 2026-05-13 — PASSED (latency < 1s, all steps)
**Owner:** Operator
**Related Gate:** ROADMAP_LIVE.md Gate 0 — *"Kill switch tested: operator can halt system within 60 seconds from Telegram"*

---

## Purpose

The kill switch is the operator's emergency-stop control. It must:

1. Halt all new order placement within **60 seconds** of activation.
2. Survive process restarts (the state must be in DB, not in-memory).
3. Generate an audit log entry that proves who activated it and when.
4. Allow safe re-activation (no half-state where paper trading is partially blocked).

This runbook walks through a planned activation/deactivation cycle to verify
all four properties before any real-money rollout.

---

## Prerequisites

- Bot is running on Railway and reachable via dashboard `/health` returning 200.
- Telegram bot is configured (`TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALERT_CHAT_ID` set).
- Operator has the Telegram chat open with the bot.
- At least one paper trading session is active (`evidence_sessions.status = 'running'`).

---

## Test Procedure

### Step 1 — Baseline (T-0)

1. Open the dashboard.
2. Verify **Safety** card shows:
   - Kill Switch: 🟢 `გამორთული — ვაჭრობა მიმდინარეობს`
   - Circuit Breaker: 🟢 `NORMAL`
3. Note the current value of `dashboard_api_key` (you don't need it for `/kill` — that uses Telegram auth — but you may need it for verification queries below).
4. Note the timestamp.

### Step 2 — Activate Kill Switch (T-0 → T-60s)

1. **Start a stopwatch.**
2. In Telegram, send `/kill` to the bot.
3. Wait for the bot's acknowledgment message. Expected response within 5 seconds:
   > `🛑 Kill switch toggled — paper_trading_enabled = false`
4. **Stop the stopwatch when ack arrives.**

**Pass criteria:** acknowledgment received within 60 seconds.

### Step 3 — Verify halt (T+5s)

Within 5 seconds of ack:

1. Refresh dashboard.
2. **Safety** card must now show:
   - Kill Switch: 🚨 `ჩართული — ვაჭრობა შეჩერებულია`
3. Run `SELECT enabled FROM feature_flags WHERE flag_name='paper_trading_enabled';`
   in the production DB — must return `false`.
4. Check the audit log for an entry:
   ```sql
   SELECT * FROM audit_log
   WHERE event_type = 'feature_flag_toggled'
   ORDER BY occurred_at DESC LIMIT 1;
   ```
   The payload should contain `{"flag": "paper_trading_enabled", "enabled": false}`.

**Pass criteria:** all three checks pass.

### Step 4 — Verify no new orders accepted

1. Trigger a synthetic signal that would normally place a paper order (e.g.
   wait for the next 15-min signal refresh — there must not have been any
   `paper_order_placed` log entries since the kill switch fired).
2. Search the JSON logs:
   ```bash
   grep '"event":"order_blocked_kill_switch"' logs/trading-bot.jsonl | tail -5
   ```
3. The strategy runner should log `"order_blocked_kill_switch"` for any signal
   that would have produced an order, with `kill_switch_active=true`.

**Pass criteria:** at least one `order_blocked_kill_switch` entry exists, and
zero new `paper_order_placed` entries between activation and now.

### Step 5 — Restart resilience

1. From Railway dashboard, click "Restart" on the service.
2. Wait for `/readyz` to return 200 again.
3. Verify the kill switch is **still active** after restart:
   - Dashboard still shows 🚨 `ჩართული`.
   - DB still shows `paper_trading_enabled = false`.

**Pass criteria:** state survived the restart (DB-backed, not in-memory).

### Step 6 — Deactivate

1. In Telegram, send `/kill` again.
2. Verify acknowledgment within 5 seconds:
   > `🟢 Kill switch toggled — paper_trading_enabled = true`
3. Refresh dashboard, confirm Safety card returns to 🟢 `გამორთული — ვაჭრობა მიმდინარეობს`.
4. Verify audit log has the second toggle entry.

**Pass criteria:** clean re-activation, no stale blocking.

### Step 7 — Confirm orders resume

1. Wait for the next signal refresh (≤15 min).
2. Search logs for a `paper_order_placed` entry after deactivation timestamp.

**Pass criteria:** new orders flow after deactivation.

---

## Recording the Result

After a successful run, append an entry to
`trading_bot/docs/runbooks/kill-switch-test-log.md`:

```
## 2026-05-DD — Kill switch test

- Operator: [name]
- Activation latency: XX seconds
- All steps pass: yes/no
- Notes: [any deviation]
- Audit log IDs: [activation, deactivation]
```

---

## Failure Modes

| Symptom | Likely Cause | Remediation |
|---------|--------------|-------------|
| `/kill` no acknowledgment within 60s | Telegram bot offline, command handler crashed | Check `TelegramCommandHandler.run()` task is alive; restart service |
| Ack received but flag stays `true` in DB | `feature_flags` table not migrated, or pool error | Run `alembic upgrade head`; check DB logs |
| Flag changes but orders still place | `is_enabled()` not checked in execution path, or TTL cache too long | Audit the execution flow; reduce feature_flag cache TTL |
| State lost on restart | Flag stored only in-memory | This is a defect — fix before any micro-live |
| Audit log entry missing | `PostgresAuditLog.append()` raised silently | Check `dashboard_audit_fetch_failed` logs |

---

## Escalation

If any test step fails:

1. **Do NOT proceed to micro-live promotion.**
2. File a bug ticket describing the failure mode.
3. Re-run this runbook after the fix lands.

A failed kill switch test blocks the entire promotion pipeline.

---

## Related

- ROADMAP_LIVE.md Gate 0 checklist
- `trading_bot/operator_console/telegram_commands.py` — `/kill` handler
- `trading_bot/compliance/pre_trade.py:_check_kill_switch` — enforcement point
- ADR-0007 — Promotion Pipeline Stages
