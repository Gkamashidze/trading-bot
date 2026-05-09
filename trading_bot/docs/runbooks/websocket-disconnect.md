# Runbook: WebSocket Disconnect

**Runbook ID:** RB-0001
**Severity:** P1
**Last Tested:** 2024-01-01 (initial creation — test in chaos environment)
**Owner:** ops
**Alert:** `websocket_reconnects_total{exchange="binance"} > 5 in 5m`

---

## Symptom

- Telegram alert: `[P1] WebSocket DISCONNECTED — binance/BTC-USDT stream offline`
- `data_feed_staleness_seconds{exchange="binance"}` rising above threshold
- Log entries: `"event": "websocket_disconnected"` appearing repeatedly
- No new market events in event bus queue

---

## Immediate Actions (< 2 minutes)

1. Check if the disconnect is affecting all symbols or just one
2. Check Binance status page: https://www.binancestatus.com/
3. If Binance is down — no action needed, bot will retry automatically
4. If only one symbol is affected — restart just that stream subscription

---

## Diagnosis

```bash
# Check recent disconnect logs
grep "websocket" logs/trading-bot.jsonl | tail -30

# Count reconnect attempts in last hour
grep "websocket_reconnect" logs/trading-bot.jsonl | wc -l

# Check metrics
curl -s http://localhost:9090/metrics | grep websocket_reconnects_total

# Check data freshness
curl -s http://localhost:9090/metrics | grep data_feed_staleness_seconds

# Test exchange connectivity
curl -s https://api.binance.com/api/v3/ping
```

**Common causes:**

| Cause | Indicator | Resolution |
|-------|-----------|------------|
| Binance maintenance | Status page shows incident | Wait for resolution |
| Network connectivity loss | `ping api.binance.com` fails | Check server network |
| Bot side rate limit | Many reconnects in short period | Check rate limit logs |
| API key invalidated | Auth error in reconnect attempt | Rotate API key |
| Firewall change | Sudden disconnect, no exchange incident | Check server firewall rules |

---

## Remediation

### Automatic Recovery (should happen without operator action)

The bot implements exponential backoff reconnection:
- Attempt 1: 2s delay
- Attempt 2: 4s delay
- Attempt 3: 8s delay
- Attempt 4: 16s delay

If reconnected within 4 attempts: no action needed.

### Manual Recovery If Auto-Reconnect Fails

```bash
# Disable WebSocket (fall back to REST polling)
# Via Telegram bot command:
/flag set websocket_enabled false

# Or via CLI:
python scripts/set_flag.py websocket_enabled false --reason "Manual recovery during disconnect incident"

# Restart the bot
systemctl restart trading-bot   # or Railway redeploy

# Re-enable WebSocket after exchange recovers
/flag set websocket_enabled true
```

### If Exchange Is Fully Down

1. Set `data_ingestion_enabled = false` to prevent failed REST fallback spam
2. Monitor exchange status
3. Re-enable when status page shows green
4. Verify data freshness after reconnect

---

## Verification

After recovery:

```bash
# Confirm reconnected
curl -s http://localhost:9090/metrics | grep 'websocket_reconnects_total'

# Confirm data is fresh
curl -s http://localhost:9090/metrics | grep 'data_feed_staleness_seconds'
# Should be < 120 for 1h timeframe

# Check latest bar in data
ls -la trading_bot/data/raw/binance/BTC_USDT/1h/
```

Expected outcome: new Parquet files updated within 2× the expected interval.

---

## Escalation

If not resolved within 30 minutes and Binance is operational:
1. Activate kill switch: `/killswitch activate`
2. Check if other exchange connections are also affected
3. Consider switching to Coinbase as backup (Stage 5b)

---

## Post-Mortem

After resolution:
- [ ] Create post-mortem in `docs/post_mortems/`
- [ ] Document the root cause
- [ ] Add this scenario to chaos catalog if not already present
- [ ] Update alert thresholds if detection was too slow

---

## Related

- ADR-0001: Event Bus Choice
- ADR-0002: Database Strategy
- Chaos scenario: `websocket-disconnect-every-60s` (Toxiproxy)
