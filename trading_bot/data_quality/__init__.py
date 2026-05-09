"""Data quality monitoring — freshness, anomaly detection, cross-source validation.

Bad data silently corrupts strategy outputs. This module enforces:
- Freshness: data older than 2x expected interval triggers an alert
- Anomaly: z-score > 5 on returns → quarantine the bar
- Cross-source: Binance vs Coinbase divergence > 0.5% → alert
"""
