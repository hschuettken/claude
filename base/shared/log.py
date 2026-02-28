"""Structured logging setup shared across all services.

Usage:
    from shared.log import get_logger
    logger = get_logger("my-service")
    logger.info("started", version="1.0")
"""

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog


def _normalize_log_event(_logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Normalize logs to: timestamp, level, service, msg, context."""
    if "msg" not in event_dict and "event" in event_dict:
        event_dict["msg"] = event_dict.pop("event")

    reserved = {"timestamp", "level", "service", "msg", "context"}
    context = event_dict.get("context")
    if not isinstance(context, dict):
        context = {} if context is None else {"value": context}

    extras = {}
    for key in list(event_dict.keys()):
        if key not in reserved:
            extras[key] = event_dict.pop(key)

    if extras:
        context.update(extras)
    event_dict["context"] = context

    return event_dict


def setup_logging(level: str = "INFO", log_format: str = "auto") -> None:
    """Configure structlog for JSON logs in containers and console logs locally."""
    is_json = log_format.lower() == "json" or (
        log_format.lower() == "auto" and not sys.stdout.isatty()
    )

    renderer = (
        structlog.processors.JSONRenderer()
        if is_json
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            _normalize_log_event,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


_initialized = False


def get_logger(service_name: str) -> structlog.stdlib.BoundLogger:
    """Get a logger bound with the service name."""
    global _initialized
    if not _initialized:
        from shared.config import Settings

        settings = Settings()
        setup_logging(settings.log_level, settings.log_format)
        _initialized = True

    return structlog.get_logger(service=service_name)
