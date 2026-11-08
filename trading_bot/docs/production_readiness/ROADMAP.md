# Production Readiness Roadmap
Last updated: 2026-11-08

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

## Before Micro-Live
- Collect at least 30 clean observed days and 100 completed round trips. Legacy
  estimates are retained but do not replace verified marked strategy evidence.
- Confirm paper/backtest parity on comparable periods and strategy scope.
- Investigate any historical audit integrity failure; never rewrite old events.
- Complete the live API permission audit and venue-specific reconciliation drill.
- Obtain a current named risk review and explicit operator approval.
- Rehearse the documented rollback and venue position-close procedure.
- Keep both live execution gates disabled until every requirement passes.

## Build Before Live
- AuditReplayer
- VaR/CVaR metrics
- Grafana dashboards
- Penetration testing

## Execution status
- Binance order submission is implemented and available only through the explicit
  gated operator workflow. It is not enabled or used by the automated runner.
- The gate is not an assertion of profitable strategy performance. SMA/RSI are
  infrastructure baselines; sentiment research has limited historical evidence.
- See ADR-0010 and the 2026-11-08 readiness/security verification record for the
  changes and remaining operational requirements.
