"""OS signal handling — graceful shutdown on SIGTERM / SIGINT.

The shutdown sequence:
1. Signal received (SIGTERM / SIGINT)
2. _shutdown_event is set
3. All async tasks listening via wait_for_shutdown() wake up
4. Each subsystem drains its queue and closes connections
5. Process exits with code 0

Kill switch (Stage 6) is a separate signal path. This module handles
only process-level OS signals.
"""

from __future__ import annotations

import asyncio
import signal

from trading_bot.observability.logging import get_logger

log = get_logger(__name__)

_shutdown_event: asyncio.Event | None = None


def _get_shutdown_event() -> asyncio.Event:
    global _shutdown_event
    if _shutdown_event is None:
        _shutdown_event = asyncio.Event()
    return _shutdown_event


def register_shutdown_handlers() -> None:
    """Register SIGTERM / SIGINT handlers. Call once in main.py."""
    loop = asyncio.get_event_loop()

    def _handle_signal(sig: signal.Signals) -> None:
        log.info(
            "shutdown_signal_received",
            signal=sig.name,
            action="initiating_graceful_shutdown",
        )
        _get_shutdown_event().set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    log.info("shutdown_handlers_registered", signals=["SIGTERM", "SIGINT"])


async def wait_for_shutdown() -> None:
    """Coroutine that completes when a shutdown signal is received."""
    await _get_shutdown_event().wait()


def is_shutdown_requested() -> bool:
    """Non-blocking check for shutdown state."""
    ev = _get_shutdown_event()
    return ev.is_set()
