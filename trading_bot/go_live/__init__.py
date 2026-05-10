"""Go-Live Readiness Gate.

Enforces a formal checklist before live trading is permitted.
All criteria must pass AND be signed off by an operator before
live_trading_enabled can be set to true.

Usage:
    from trading_bot.go_live import GoLiveGate
    gate = GoLiveGate(audit_log=audit_log, exchange=exchange)
    report = await gate.evaluate()
    if report.ready:
        # All criteria passed — operator may now enable the live flag
        ...
"""

from trading_bot.go_live.criteria import (
    CriterionResult,
    CriterionStatus,
    GoLiveCriterion,
    ReadinessReport,
)
from trading_bot.go_live.gate import GoLiveGate

__all__ = [
    "CriterionResult",
    "CriterionStatus",
    "GoLiveCriterion",
    "GoLiveGate",
    "ReadinessReport",
]
