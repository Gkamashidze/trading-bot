"""Paper Testing Evidence Store package.

Public API:
    init_evidence_store(pool)          — call once at startup
    get_evidence_store()               — return the module-level EvidenceStore
    set_current_session_id(uuid)       — store the active session UUID
    get_current_session_id()           — retrieve the active session UUID
"""

from trading_bot.evidence.store import (
    EvidenceStore,
    get_current_session_id,
    get_evidence_store,
    init_evidence_store,
    set_current_session_id,
)

__all__ = [
    "EvidenceStore",
    "get_current_session_id",
    "get_evidence_store",
    "init_evidence_store",
    "set_current_session_id",
]
