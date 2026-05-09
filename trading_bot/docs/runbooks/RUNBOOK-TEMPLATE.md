# Runbook: [Incident Title]

**Runbook ID:** RB-XXXX
**Severity:** P0 | P1 | P2 | P3
**Last Tested:** YYYY-MM-DD
**Owner:** [team/person]
**Alert:** [Link to Prometheus/Grafana alert that fires this runbook]

---

## Symptom

What does the operator see? What alert fired? What is the user impact?

_Example: "Telegram alert: 'WebSocket disconnected — Binance BTCUSDT stream offline for > 30s'"_

---

## Immediate Actions (< 2 minutes)

Steps to take in the first 2 minutes to limit blast radius:

1. Step one
2. Step two
3. Step three

---

## Diagnosis

How to determine root cause:

```bash
# Check logs
grep "websocket_disconnect" logs/trading-bot.jsonl | tail -20

# Check metrics
curl http://localhost:9090/metrics | grep websocket_reconnects

# Check exchange status
curl https://www.binancestatus.com/api/v2/summary.json
```

Common causes and their indicators:

| Cause | Indicator |
|-------|-----------|
| Exchange outage | Binance status page shows incident |
| Network issue | Other exchange connections also dropping |
| API key expired | Auth error in logs |
| Rate limit exceeded | 429 errors before disconnect |

---

## Remediation

Steps to resolve the issue:

### If Exchange Outage
1. Enable `websocket_enabled = false` feature flag
2. Switch to REST polling mode
3. Monitor exchange status page
4. Re-enable when incident resolved

### If Network Issue
1. Check server connectivity: `ping api.binance.com`
2. Check DNS: `nslookup api.binance.com`
3. Restart networking if needed
4. Check VPS provider status

### If API Key Expired
1. Generate new API key on exchange (read-only)
2. Update `BINANCE_API_KEY` environment variable
3. Restart the bot
4. Rotate secret in Doppler/Vault if Phase 2+

---

## Verification

How to confirm the issue is resolved:

```bash
# Check reconnection metric
curl http://localhost:9090/metrics | grep websocket_reconnects_total

# Check data freshness
curl http://localhost:9090/metrics | grep data_feed_staleness_seconds

# Verify latest bar timestamp
python scripts/check_data_freshness.py BTC/USDT 1h
```

Expected outcome: `data_feed_staleness_seconds < 120` for 1h timeframe.

---

## Escalation

If not resolved within 30 minutes:
1. Activate kill switch via Telegram command: `/killswitch activate`
2. Contact [escalation contact]

---

## Post-Mortem

After resolution:
- [ ] Create post-mortem document in `docs/post_mortems/`
- [ ] Add failure scenario to chaos catalog
- [ ] Update this runbook if steps were incorrect
- [ ] Add monitoring improvement if detection was slow

---

## Related

- ADR-0001: Event Bus Choice
- Runbook: exchange-api-outage.md
- Alert: `websocket_reconnects_total > 5 in 5m`
