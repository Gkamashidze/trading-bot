# Binance IP Ban Recovery

## Trigger

Telegram alert `exchange_banned: binance`, `funding_rate_skipped_ban_active`, or stale
Binance 1h candles following an HTTP 418 / error code `-1003`.

## Immediate Safety

- Signal generation must remain skipped while Binance OHLCV data is stale.
- Do not manually trigger backfills or restart the service during the active ban window.
- Read `banned until <epoch-ms>` in the Railway trace and convert it to UTC.

## Diagnosis

Search Railway logs immediately before the first `exchange_circuit_tripped` event:

- `exchange_rate_limit_blocked` indicates the app received a `429` and stopped requests.
- `exchange_rate_limit_warning` or `exchange_rate_limit_critical` indicates high IP weight.
- A direct `418` without preceding weight events indicates an IP already rate-limited
  outside the observed process, such as shared outbound egress.

Binance limits REST traffic by source IP rather than API key. Railway outbound IPs may
be shared, so application throttling cannot fully protect a shared address.

## Recovery

1. Wait until the logged `banned until` timestamp has expired.
2. Confirm the next scheduled 1h ingestion writes fresh BTC/USDT and ETH/USDT bars.
3. Confirm stale-signal alerts stop after the next signal refresh.
4. If bans recur without local rate-limit warnings, move Binance REST egress to a
   dedicated outbound proxy or host; Railway static outbound IP is not guaranteed dedicated.

## Implemented Guardrails

- One process-wide Binance REST request slot prevents concurrent jobs extending a detected ban.
- HTTP 429 honors `Retry-After` without automatic retries.
- Ban and Retry-After state is persisted alongside `DATA_PATH` across deploy restarts.
- BTC/ETH hourly ingestion startup times are staggered.
- OHLCV retrieval calls the spot kline endpoint directly and avoids redundant market metadata
  loads for each short-lived ingestion adapter.
