# Production Readiness Roadmap
Last updated: 2026-05-11

## Gate Requirements Before Micro-Live
- 30+ calendar days of paper trading
- 100+ paper trades recorded
- Zero CRITICAL reconciliation events
- Parity score >= 70/100
- Risk operator sign-off in audit log

## Implemented
- trading_bot/parity/report.py
- trading_bot/compliance/pre_trade.py
- trading_bot/execution/post_trade.py
- trading_bot/promotion/micro_live.py
- trading_bot/monitoring/decay.py
- trading_bot/state/risk_state.py (InMemoryRiskStateStore + PostgresRiskStateStore)
- trading_bot/exchange/precision.py
- trading_bot/exchange/fake_exchange.py
- trading_bot/orderbook/models.py
- trading_bot/execution/router.py — `_last_signal` persisted to `/data/last_signal.json`
- trading_bot/data/lineage.py — `LineageStore` persisted to `/data/lineage_store.json`
107 unit tests, ruff + mypy clean.

## Build Before Micro-Live
- BinanceOrderBookProvider
- GoLiveGate.evaluate()

## Build Before Live
- AuditReplayer
- VaR/CVaR metrics
- Grafana dashboards
- Penetration testing

## Blocked Until Stage 5
- BinanceExchange.place_order() raises NotImplementedError
- replace_order() not implemented
