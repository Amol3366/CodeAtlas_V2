"""structlog configuration (CLAUDE.md §3, §13).

Structured events with a bound ``repository_id`` (and later ``snapshot_id``)
context. Never log secrets or raw source marked sensitive — callers pass only
event names and safe metadata. Configuration is idempotent so repeated calls
(tests, CLI, API) do not stack processors.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog

_LEVELS: dict[str, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def configure_logging(*, level: str = "INFO", fmt: str = "json") -> None:
    """Configure structlog once. ``fmt`` is ``json`` (production) or ``console`` (dev)."""
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if fmt == "json" else structlog.dev.ConsoleRenderer()
    )
    min_level = _LEVELS.get(level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(min_level),
        cache_logger_on_first_use=True,
    )


def get_logger(**initial_context: Any) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, optionally pre-bound with context (e.g. repository_id)."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger()
    if initial_context:
        return logger.bind(**initial_context)
    return logger
