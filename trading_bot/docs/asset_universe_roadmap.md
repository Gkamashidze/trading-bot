# Asset Universe Expansion Roadmap
Last updated: 2026-05-11

> **Hard constraint:** `live_trading_enabled = false` at all times.
> All new assets start as `disabled` or `research` and must pass the
> promotion gates below before advancing to `paper` status.

---

## Architecture

The asset universe is defined in a single YAML file:

```
trading_bot/config/asset_universe.yaml
```

The file is loaded once at startup by `AssetUniverseRegistry` (cached via
`functools.lru_cache`). Every subsystem reads from the registry rather than
hardcoded symbol lists. Each asset carries:

| Field | Purpose |
|---|---|
| `symbol` | Exchange-normalised symbol (e.g. `BTC/USDT`, `SPY`) |
| `venue` | `binance` or `alpaca` |
| `asset_class` | `crypto`, `etf`, `equity` |
| `status` | `disabled` → `research` → `paper` → `micro_live_candidate` → `live_candidate` |
| `phase` | Expansion phase 1–5 |
| `max_capital_pct` | Hard portfolio allocation cap |
| `max_order_notional_usd` | Hard single-order size cap |
| `min_24h_volume_usd` | Minimum liquidity gate |
| `max_spread_bps` | Maximum acceptable spread |
| `required_history_days` | Clean OHLCV days required before paper promotion |
| `paper_min_days` | Minimum paper-trading observation days for evidence gate |
| `paper_min_trades` | Minimum paper trades for evidence gate |
| `enabled_strategies` | Strategy IDs allowed on this asset |
| `feature_flag` | DB feature flag that gates activation of this group |
| `experimental` | Excluded from default paper universe if `true` |

---

## Promotion Gates

```
disabled
   │
   │  flip feature flag (asset_group_* = true)
   ▼
research
   │
   │  1. required_history_days clean OHLCV stored
   │  2. data quality / freshness checks pass
   │  3. liquidity gate: 24h volume > min_24h_volume_usd
   │  4. spread gate: spread < max_spread_bps
   ▼
paper
   │
   │  1. paper_min_days of evidence collected
   │  2. paper_min_trades executed in evidence store
   │  3. max_drawdown_pct < EvidenceSettings.max_drawdown_pct
   │  4. parity score >= EvidenceSettings.min_parity_score
   │  5. no CRITICAL reconciliation events
   │  6. operator sign-off in audit log
   ▼
micro_live_candidate   ← human review required
   │
   │  (live_trading_enabled must be true — globally disabled)
   ▼
live_candidate         ← not reachable until live trading is enabled
```

---

## Expansion Phases

### Phase 1 — Current Paper Universe (Active)

| Symbol | Venue | Cap | Status |
|---|---|---|---|
| BTC/USDT | Binance | 30% | ✅ paper |
| ETH/USDT | Binance | 25% | ✅ paper |

**Why BTC/ETH first:**
Deepest liquidity, longest historical data (2017), lowest spread (~1–2 bps).
Both are reference assets for crypto-market beta. Strategy validation is
most reliable on the most liquid market first.

**Feature flag:** `asset_group_crypto_phase1_enabled = true` (already on)

---

### Phase 2 — SOL/USDT (Research → Paper candidate)

| Symbol | Venue | Cap | Status | Gate |
|---|---|---|---|---|
| SOL/USDT | Binance | 20% | 🔬 research | 180d OHLCV + flag flip |

**Why SOL:**
- Top-5 market cap, $1–3 B/day Binance volume
- BTC correlation ≈ 0.75 (provides diversification vs ETH at 0.85+)
- High-throughput L1 with distinct DeFi/NFT demand drivers
- yfinance + Binance CCXT data available since 2020

**Liquidity expectations:**  
Good. Binance USDT pair consistently ranks in top-5 spot volume.

**Spread/slippage:**  
Typically 2–5 bps. Widen to 10–15 bps during weekend thinning. Manageable
for daily-bar strategies; requires intraday monitoring for 1h strategies.

**Volatility profile:**  
Annualised vol ≈ 100–130% vs BTC ≈ 75–90%. Daily ranges frequently 5–10%.
Sizing model must use volatility-scaled position sizing.

**Strategy suitability:**  
SMA crossover — well suited (trending asset). RSI mean-reversion — higher
risk due to momentum-driven tail events; defer to Phase 3.

**Risk cap rationale:** 20% — meaningful diversification without
overweighting a single L1 that has had network outages.

**Exclusion / delay reasons:**
- Network outage history (2021–2022): defer if uptime concern resurfaces
- Regulatory uncertainty: monitor for exchange-specific delisting risk
- Activate only after 180 days of clean Binance OHLCV data are stored

**Paper testing requirements:**
- 45 calendar days observation
- 30 paper trades
- Zero data gaps > 25 hours
- Max drawdown < 20%

**Feature flag:** `asset_group_crypto_phase2_enabled` — flip after data gate passes

---

### Phase 3 — BNB/USDT + XRP/USDT (Disabled)

| Symbol | Venue | Cap | Status | Special risk |
|---|---|---|---|---|
| BNB/USDT | Binance | **10%** | ⏸ disabled | Binance ecosystem concentration |
| XRP/USDT | Binance | **10%** | ⏸ disabled | Regulatory / news sensitivity |

**BNB rationale:**
Exchange token — strong Binance ecosystem utility. Deep spot liquidity on
home exchange. **Lower cap (10%) enforced because BNB price is perfectly
correlated with Binance health: an exchange outage means simultaneous
position loss AND broker unavailability.** Both risks materialise at the
same moment. Treat BNB as a concentrated venue bet, not crypto diversification.

**XRP rationale:**
Large retail and institutional liquidity. Cross-border payment narrative
gives differentiated demand. **Lower cap (10%) enforced because binary
headline risk from regulatory actions (SEC lawsuit history) can move price
20–40% in hours with no technical warning.** Must implement circuit-breaker
on unusual volatility pre-news.

**Activation gate:** Complete Phase 2 paper evidence first. Then:
1. 180 days clean OHLCV
2. Regulatory monitoring: no active SEC/CFTC enforcement against the asset
3. Liquidity gate: 24h volume > $50 M on Binance
4. Feature flag: `asset_group_crypto_phase3_enabled`

**Feature flag:** `asset_group_crypto_phase3_enabled` (default: false)

---

### Phase 4 — LINK/USDT (Disabled)

| Symbol | Venue | Cap | Status | Gate |
|---|---|---|---|---|
| LINK/USDT | Binance | 15% | ⏸ disabled | Phase 3 gates + 180d OHLCV |

**Why LINK:**
Decentralised oracle leader with strong institutional usage (Aave, Compound,
Synthetix all depend on Chainlink). Demand is tied to smart-contract data
consumption rather than speculation alone — provides a fundamentally distinct
signal driver from BTC/ETH.

**Liquidity expectations:**
$30–100 M/day Binance USDT volume. Lower than Phase 1–3 assets.
Spread widens to 8–15 bps during thin hours.

**Volatility profile:**
Annualised vol ≈ 120%. BTC correlation ≈ 0.70.

**Activation gate:** Phase 3 paper evidence complete first.

**Feature flag:** `asset_group_crypto_phase4_enabled` (default: false)

---

### Phase 5 — ETF Basket via Alpaca (Disabled)

| Symbol | Venue | Cap | Rationale |
|---|---|---|---|
| SPY | Alpaca | 30% | S&P 500 anchor — most liquid ETF globally |
| QQQ | Alpaca | 25% | Nasdaq-100 — tech/growth signal |
| SOXX | Alpaca | 15% | Semiconductor sector — AI cycle exposure |
| IWM | Alpaca | 15% | Russell 2000 — economic cycle diversification |
| TLT | Alpaca | 20% | Long-duration Treasury — risk-off hedge |
| GLD | Alpaca | 15% | Gold — inflation hedge, low crypto correlation |

**Why this basket:**
Portfolio construction goal is a cross-asset universe where equity beta
(SPY/QQQ), small-cap cyclicality (IWM), sector rotation (SOXX), duration
risk (TLT), and inflation protection (GLD) can produce signals independent
of crypto momentum. The basket covers 6 distinct factor exposures.

**Key differences from crypto:**
- Market hours: 09:30–16:00 ET only (NYSE/Nasdaq calendar required)
- Market maker structure: ~1 bps spread vs ~3–10 bps crypto
- T+2 settlement (vs near-instant crypto)
- Corporate actions: dividends, splits — require AdjustedClose handling
- Fractional shares: Alpaca supports; position sizing differs

**Hard gates before any ETF can activate:**
1. Alpaca paper API integration complete (Stage 5 execution engine)
2. NYSE/Nasdaq trading calendar implemented in `trading_bot/calendars/`
3. yfinance adjusted-close OHLCV backfill complete (365 days minimum)
4. Separate paper portfolio tracking for equities vs crypto
5. Feature flag: `asset_group_etf_phase5_enabled`

**Correlation notes:**
- SPY vs BTC: −0.1 to +0.3 (highly regime-dependent)
- TLT vs BTC: typically negative in risk-off; breaks down in 2022-style
  rate-shock environments
- GLD vs BTC: ~0.1 (nearly independent)
- SOXX vs ETH: +0.4 to +0.6 in growth regimes (correlated tech sentiment)

**Feature flag:** `asset_group_etf_phase5_enabled` (default: false)

---

### DOGE/USDT — Experimental Only

| Symbol | Cap | Status | Flag |
|---|---|---|---|
| DOGE/USDT | **5%** | ⏸ disabled | `asset_experimental_doge_enabled` |

- Hard-capped at 5%
- Separate feature flag isolated from phase flags
- Not part of the default paper universe
- Requires 90-day paper observation before any promotion review
- `experimental: true` in registry — excluded from standard backtesting runs
- Activation only with explicit quant team sign-off in audit log

**Exclusion rationale:**
No fundamental demand floor. Price driven by social-media sentiment (celebrity
tweets have moved price 30%+ in minutes). Not suitable for systematic strategies
without a dedicated social-signal pipeline.

---

## Risk Cap Summary

| Asset | Max Capital | Max Order | Rationale |
|---|---|---|---|
| BTC/USDT | 30% | $10,000 | Deepest market; anchor position |
| ETH/USDT | 25% | $8,000 | High liquidity; BTC-correlated |
| SOL/USDT | 20% | $5,000 | Diversification; network risk |
| BNB/USDT | **10%** | $3,000 | Binance ecosystem concentration |
| XRP/USDT | **10%** | $3,000 | Regulatory binary risk |
| LINK/USDT | 15% | $4,000 | Lower liquidity; Phase 4 |
| DOGE/USDT | **5%** | $1,000 | Experimental; meme risk |
| SPY | 30% | $15,000 | Most liquid ETF; anchor |
| QQQ | 25% | $12,000 | Tech-heavy; SPY-correlated |
| SOXX | 15% | $5,000 | Sector concentration |
| IWM | 15% | $5,000 | Small-cap liquidity risk |
| TLT | 20% | $8,000 | Duration risk |
| GLD | 15% | $5,000 | Low yield; storage cost |

---

## Data Ingestion Plan

| Phase | Symbols | Source | Backfill Required |
|---|---|---|---|
| 1 (active) | BTC/USDT, ETH/USDT | Binance CCXT | Done (2017–present) |
| 2 | SOL/USDT | Binance CCXT | 2020–present (≈ 1600 days) |
| 3 | BNB/USDT, XRP/USDT | Binance CCXT | 2017–present |
| 4 | LINK/USDT | Binance CCXT | 2017–present |
| 5 (ETFs) | SPY/QQQ/SOXX/IWM/TLT/GLD | yfinance (AdjustedClose) | 1993–present for SPY; 1999+ for others |

Backfill for phase 2–4 can run via `POST /admin/backfill?symbol=SOL/USDT&days_back=1800`
once the feature flag is enabled and data ingestion is on.

---

## Evidence Store Requirements Before Micro-Live Review

Each asset must accumulate, in `paper` status:

| Metric | Minimum |
|---|---|
| Calendar days observed | As per `paper_min_days` per asset |
| Paper trades | As per `paper_min_trades` per asset |
| Max daily drawdown | < 20% |
| Reconciliation events | Zero CRITICAL |
| Parity score | ≥ 70/100 |
| Data freshness gaps | No gap > 25 hours |

Review is gated by human operator sign-off in the audit log. Live trading
remains globally disabled until `live_trading_enabled` is explicitly flipped.

---

## Implementation Status

| Deliverable | Status |
|---|---|
| `trading_bot/asset_universe/registry.py` | ✅ Done |
| `trading_bot/config/asset_universe.yaml` | ✅ Done |
| `trading_bot/config/feature_flags.yaml` (asset flags added) | ✅ Done |
| `trading_bot/dashboard/app.py` (`_ALLOWED_SYMBOLS` → registry) | ✅ Done |
| `/partials/asset_universe` dashboard endpoint | ✅ Done |
| `dashboard/templates/partials/asset_universe.html` | ✅ Done |
| `index.html` (Asset Universe card added) | ✅ Done |
| `tests/unit/test_asset_universe.py` (22 tests) | ✅ Done |
| `trading_bot/docs/asset_universe_roadmap.md` (this file) | ✅ Done |

All new assets are `disabled` or `research`. Live trading remains disabled.
