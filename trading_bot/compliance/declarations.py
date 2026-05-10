"""Legal/Compliance Boundary Documentation — Feature #15.

Machine-readable declarations that codify the legal and operational
boundaries of this trading system. These declarations are:

  1. Surfaced in operator dashboards and audit logs at startup
  2. Versioned alongside the codebase (changes require PR review)
  3. Referenced by runbooks and post-mortem templates

IMPORTANT: This module makes no legal guarantees. Consult a qualified
attorney for jurisdiction-specific regulatory requirements.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class DeclarationCategory(StrEnum):
    LEGAL = "legal"
    OPERATIONAL = "operational"
    DATA_RETENTION = "data_retention"
    REGULATORY = "regulatory"


@dataclass(frozen=True)
class ComplianceDeclaration:
    """A single, versioned compliance declaration."""

    declaration_id: str
    category: DeclarationCategory
    title: str
    body: str
    version: str = "1.0"
    requires_operator_ack: bool = False


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------

_DECLARATIONS: list[ComplianceDeclaration] = [
    ComplianceDeclaration(
        declaration_id="LEGAL-001",
        category=DeclarationCategory.LEGAL,
        title="Proprietary Trading — Own Capital Only",
        body=(
            "This system trades exclusively with the operator's own capital. "
            "No client funds, pooled capital, or third-party assets are managed "
            "by this system at any time. The operator bears full financial risk."
        ),
        version="1.0",
        requires_operator_ack=True,
    ),
    ComplianceDeclaration(
        declaration_id="LEGAL-002",
        category=DeclarationCategory.LEGAL,
        title="No Investment Advisory Services",
        body=(
            "This system does not provide investment advice, recommendations, "
            "or signals to any third party. All outputs are for the sole use of "
            "the system operator. This is not a registered investment adviser."
        ),
        version="1.0",
        requires_operator_ack=True,
    ),
    ComplianceDeclaration(
        declaration_id="OPS-001",
        category=DeclarationCategory.OPERATIONAL,
        title="Operator Responsibility for Live Trading",
        body=(
            "The operator is solely responsible for monitoring the system during "
            "live trading sessions, setting appropriate position size limits, and "
            "triggering the kill-switch if the system behaves unexpectedly. "
            "Automated safeguards (circuit breaker, kill flag) supplement but do "
            "not replace human oversight."
        ),
        version="1.0",
        requires_operator_ack=True,
    ),
    ComplianceDeclaration(
        declaration_id="OPS-002",
        category=DeclarationCategory.OPERATIONAL,
        title="No Live Trading Before Stage 5 Promotion",
        body=(
            "Live order placement is disabled until the strategy has completed the "
            "full promotion pipeline: SHADOW → PAPER → MICRO_LIVE → LIVE. "
            "Bypassing the promotion pipeline is a configuration violation."
        ),
        version="1.0",
        requires_operator_ack=False,
    ),
    ComplianceDeclaration(
        declaration_id="DATA-001",
        category=DeclarationCategory.DATA_RETENTION,
        title="Trade Record Retention — Minimum 7 Years",
        body=(
            "All executed trade records, order logs, and portfolio snapshots must "
            "be retained for a minimum of 7 years from the trade date. This applies "
            "to both paper and live trades. Deletion requires explicit operator action "
            "and must be logged in the audit trail."
        ),
        version="1.0",
        requires_operator_ack=False,
    ),
    ComplianceDeclaration(
        declaration_id="DATA-002",
        category=DeclarationCategory.DATA_RETENTION,
        title="Audit Log Immutability",
        body=(
            "Audit logs are append-only. No record may be modified or deleted after "
            "creation. Any attempt to alter audit records is a critical security "
            "incident and must be escalated immediately."
        ),
        version="1.0",
        requires_operator_ack=False,
    ),
    ComplianceDeclaration(
        declaration_id="REG-001",
        category=DeclarationCategory.REGULATORY,
        title="Exchange API Terms of Service Compliance",
        body=(
            "The operator is responsible for ensuring that all trading activity "
            "complies with the terms of service of the connected exchanges (Binance, "
            "Alpaca). Automated trading may be subject to exchange-specific rules "
            "including rate limits, position limits, and prohibited strategies."
        ),
        version="1.0",
        requires_operator_ack=True,
    ),
    ComplianceDeclaration(
        declaration_id="REG-002",
        category=DeclarationCategory.REGULATORY,
        title="Tax Reporting Obligation",
        body=(
            "The operator is solely responsible for calculating and reporting all "
            "taxable events arising from trading activity. The accounting ledger "
            "provides P&L data for reference; it does not constitute tax advice. "
            "Consult a qualified tax professional in your jurisdiction."
        ),
        version="1.0",
        requires_operator_ack=False,
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_compliance_declarations(
    category: DeclarationCategory | None = None,
) -> list[ComplianceDeclaration]:
    """Return all compliance declarations, optionally filtered by category."""
    if category is None:
        return list(_DECLARATIONS)
    return [d for d in _DECLARATIONS if d.category == category]


def get_declarations_requiring_ack() -> list[ComplianceDeclaration]:
    """Return declarations that require explicit operator acknowledgement."""
    return [d for d in _DECLARATIONS if d.requires_operator_ack]


def get_declaration_by_id(declaration_id: str) -> ComplianceDeclaration | None:
    for d in _DECLARATIONS:
        if d.declaration_id == declaration_id:
            return d
    return None
