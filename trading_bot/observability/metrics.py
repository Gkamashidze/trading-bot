"""Prometheus metrics definitions.

All metrics are defined here as module-level singletons so they can be
imported from anywhere without double-registration errors.

Metrics follow the naming convention: {namespace}_{subsystem}_{name}_{unit}.

Prometheus endpoint is started in main.py via start_metrics_server().
"""

from __future__ import annotations

import threading

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

# ── Latency histograms (per v5 spec) ─────────────────────────────────────────

API_LATENCY = Histogram(
    "trading_api_latency_seconds",
    "Exchange API call latency",
    labelnames=["exchange", "method"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

ORDER_SUBMIT_TO_ACK = Histogram(
    "trading_order_submit_to_ack_seconds",
    "Latency from order submission to exchange acknowledgement",
    labelnames=["exchange", "symbol"],
    buckets=(0.01, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0),
)

SIGNAL_TO_FILL = Histogram(
    "trading_signal_to_fill_seconds",
    "End-to-end latency from signal generation to order fill",
    labelnames=["strategy", "exchange", "symbol"],
    buckets=(0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0),
)

SIGNAL_GENERATION_LATENCY = Histogram(
    "trading_signal_generation_seconds",
    "Strategy signal generation latency",
    labelnames=["strategy"],
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5),
)

RISK_CHECK_LATENCY = Histogram(
    "trading_risk_check_seconds",
    "Risk engine evaluation latency",
    buckets=(0.001, 0.005, 0.01, 0.02, 0.05, 0.1),
)

# ── Gauges ────────────────────────────────────────────────────────────────────

DATA_FEED_STALENESS = Gauge(
    "trading_data_feed_staleness_seconds",
    "Seconds since last market data update",
    labelnames=["exchange", "symbol", "timeframe"],
)

RECONCILIATION_DRIFT = Gauge(
    "trading_reconciliation_drift",
    "Number of positions with OMS/exchange state mismatch",
    labelnames=["exchange"],
)

DAILY_DRAWDOWN_PCT = Gauge(
    "trading_daily_drawdown_pct",
    "Current daily drawdown as a fraction (0.05 = 5%)",
)

STRATEGY_PNL = Gauge(
    "trading_strategy_pnl_usd",
    "Realised + unrealised PnL per strategy in USD",
    labelnames=["strategy"],
)

EVENT_BUS_QUEUE_DEPTH = Gauge(
    "trading_event_bus_queue_depth",
    "Number of events waiting in the bus queue",
    labelnames=["event_type"],
)

DB_POOL_UTILIZATION = Gauge(
    "trading_db_pool_utilization",
    "Fraction of DB connection pool in use (0-1)",
)

MEMORY_USAGE_BYTES = Gauge(
    "trading_memory_usage_bytes",
    "Process RSS memory in bytes",
)

# ── Counters ──────────────────────────────────────────────────────────────────

ORDERS_SUBMITTED = Counter(
    "trading_orders_submitted_total",
    "Total orders submitted to exchange",
    labelnames=["exchange", "symbol", "side", "strategy"],
)

ORDERS_FILLED = Counter(
    "trading_orders_filled_total",
    "Total orders filled",
    labelnames=["exchange", "symbol", "side", "strategy"],
)

ORDERS_REJECTED = Counter(
    "trading_orders_rejected_total",
    "Total orders rejected by exchange",
    labelnames=["exchange", "reason"],
)

WEBSOCKET_RECONNECTS = Counter(
    "trading_websocket_reconnects_total",
    "Total WebSocket reconnection events",
    labelnames=["exchange", "stream"],
)

FEATURE_FLAG_EVALUATIONS = Counter(
    "trading_feature_flag_evaluations_total",
    "Total feature flag evaluations",
    labelnames=["flag_name", "result"],
)

IDEMPOTENCY_HITS = Counter(
    "trading_idempotency_hits_total",
    "Total idempotency key cache hits (duplicate requests blocked)",
)

KILL_SWITCH_ACTIVATIONS = Counter(
    "trading_kill_switch_activations_total",
    "Total kill switch activations",
    labelnames=["reason"],
)

DATA_ANOMALIES_DETECTED = Counter(
    "trading_data_anomalies_detected_total",
    "Total data anomalies detected",
    labelnames=["exchange", "symbol", "anomaly_type"],
)

FILL_COUNT = Counter(
    "trading_fills_total",
    "Total confirmed fills",
    labelnames=["symbol", "side", "environment", "partial"],
)

FILL_NOTIONAL = Histogram(
    "trading_fill_notional_usd",
    "Fill notional value in USD",
    labelnames=["symbol", "environment"],
    buckets=[10, 50, 100, 500, 1000, 5000, 10000, 50000],
)

FILL_SLIPPAGE_BPS = Histogram(
    "trading_fill_slippage_bps",
    "Fill slippage in basis points",
    labelnames=["symbol"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 25, 50, 100],
)

# ── Prometheus server ─────────────────────────────────────────────────────────

_metrics_started = False
_metrics_lock = threading.Lock()


def start_metrics_server(port: int = 9090) -> None:
    """Start the Prometheus HTTP metrics server. Idempotent."""
    global _metrics_started
    with _metrics_lock:
        if not _metrics_started:
            start_http_server(port)
            _metrics_started = True
