"""Structured logging setup shared across all services.

Usage:
    from shared.logging import get_logger
    logger = get_logger("my-service")
    logger.info("started", version="1.0")
"""

import logging
import sys

import structlog


def setup_logging(level: str = "INFO") -> None:
    """Configure structlog with console-friendly output."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
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
        setup_logging(settings.log_level)
        _initialized = True

    return structlog.get_logger(service=service_name)
