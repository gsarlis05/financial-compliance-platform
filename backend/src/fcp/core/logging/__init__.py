"""Structured JSON logging with redaction.

Application code logs with ``structlog.get_logger(__name__)`` and passes identifiers only, e.g.
``log.info("entry.posted", entity_id=..., count=3)``. Values of keys outside the allow-list in
``redaction.py`` are replaced with ``[REDACTED]``.
"""

from typing import Any

import structlog

from .redaction import ALLOWED_KEYS, REDACTED, redact_event_dict, scrub

_SHARED_PROCESSORS: list[Any] = [
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
]


def json_formatter() -> structlog.stdlib.ProcessorFormatter:
    """Formatter that renders both structlog and stdlib records as redacted JSON lines."""
    return structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=_SHARED_PROCESSORS,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            redact_event_dict,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
    )


def configure_structlog() -> None:
    structlog.configure(
        processors=[
            *_SHARED_PROCESSORS,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def build_logging_config(level: str = "INFO") -> dict[str, Any]:
    """Django ``LOGGING`` dict: every record goes through the redacting JSON formatter."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": json_formatter}},
        "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            # Django's request logger duplicates our own request/exception logging.
            "django.request": {"level": "ERROR", "propagate": True},
            "django.server": {"level": "WARNING", "propagate": True},
        },
    }


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


__all__ = [
    "ALLOWED_KEYS",
    "REDACTED",
    "build_logging_config",
    "configure_structlog",
    "get_logger",
    "json_formatter",
    "redact_event_dict",
    "scrub",
]
