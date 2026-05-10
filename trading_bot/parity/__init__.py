"""Paper/Live Parity Reporting — #2 of the production readiness roadmap.

Compares backtest vs paper and paper vs live performance to detect systematic
deviations before and after promotion. Micro-live promotion requires an
acceptable parity score (default: >= 70/100).
"""

from trading_bot.parity.report import (
    ParityMetrics,
    ParityReport,
    ParityScorer,
    ParityScoringConfig,
    StrategySnapshot,
)

__all__ = [
    "ParityMetrics",
    "ParityReport",
    "ParityScorer",
    "ParityScoringConfig",
    "StrategySnapshot",
]
