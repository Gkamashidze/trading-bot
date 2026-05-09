"""Structured logging setup using structlog.

Features:
- JSON output in production, colored console output in development
- Correlation ID automatically injected into every log entry via contextvars
- Runbook URL embedded in every ERROR/CRITICAL log
- No print() — structlog only
- Secrets are never logged (callers must redact before passing to logger)

Usage:
    from trading_bot.observability.logging import get_logger, bind_correlation_id

    log = get_logger(__name__)

    async def my_handler(correlation_id: str) -> None:
        bind_correlation_id(correlation_id)
        log.info("processing", symbol="BTC/USDT")
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# ContextVar carries the correlation ID across async tasks
_correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
_strategy_id_var: ContextVar[str] = ContextVar("strategy_id", default="")


def bind_correlation_id(correlation_id: str) -> None:
    """Bind a correlation ID to the current async context."""
    _correlation_id_var.set(correlation_id)


def bind_strategy_id(strategy_id: str) -> None:
    """Bind a strategy ID to the current async context."""
    _strategy_id_var.set(strategy_id)


def get_correlation_id() -> str:
    return _correlation_id_var.get()


def _inject_context_vars(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor: inject correlation_id from ContextVar."""
    cid = _correlation_id_var.get()
    if cid:
        event_dict["correlation_id"] = cid
    sid = _strategy_id_var.get()
    if sid:
        event_dict["strategy_id"] = sid
    return event_dict


def _inject_runbook(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Structlog processor: embed runbook URL in error/critical logs."""
    if method_name in ("error", "critical", "exception"):
        if "runbook_url" not in event_dict:
            event_dict["runbook_url"] = (
                "https://github.com/Gkamashidze/trading-bot/tree/main/trading_bot/docs/runbooks"
            )
    return event_dict


def configure_logging(
    level: str = "INFO",
    fmt: str = "json",
    include_caller: bool = False,
) -> None:
    """Configure structlog + stdlib logging.

    Call once at application startup (main.py) before any logging occurs.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Shared processors for both stdlib and structlog
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _inject_context_vars,
        _inject_runbook,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    if include_caller:
        shared_processors.append(structlog.processors.CallsiteParameterAdder(
            [
                structlog.processors.CallsiteParameter.FILENAME,
                structlog.processors.CallsiteParameter.FUNC_NAME,
                structlog.processors.CallsiteParameter.LINENO,
            ]
        ))

    if fmt == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)

    # Quieten noisy libraries
    for noisy in ("asyncio", "ccxt", "aiohttp", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to the given module name."""
    return structlog.get_logger(name)  # type: ignore[return-value]
