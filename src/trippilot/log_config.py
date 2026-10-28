"""Structured JSON logging with redaction of sensitive keys (threat T-01-04, Pitfall 6)."""

from __future__ import annotations

import logging
from typing import Any

import structlog
from structlog.typing import EventDict, WrappedLogger

MASK = '***'

SENSITIVE_KEYS = frozenset(
    {
        'token',
        'secret',
        'authorization',
        'payment_token',
        'vault_id',
        'code',
        'state',
        'password',
        'cookie',
        'invite',
    }
)
"""Keys whose values are always masked, compared case-insensitively."""

_SENSITIVE_FRAGMENTS = ('token', 'secret', 'password')
"""Keys containing one of these (for example `access_token`) are masked as well."""


def _is_sensitive(key: str) -> bool:
    """Return True when the log key must have its value masked."""
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or any(part in lowered for part in _SENSITIVE_FRAGMENTS)


def _redact(value: Any) -> Any:
    """Return a copy of value with sensitive dict entries masked, recursing into containers."""
    if isinstance(value, dict):
        return {
            key: MASK if isinstance(key, str) and _is_sensitive(key) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [_redact(item) for item in value]
    return value


def redact_sensitive(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    """Structlog processor that masks the values of sensitive keys, nested ones included."""
    redacted: EventDict = _redact(event_dict)
    return redacted


def configure_logging() -> None:
    """Configure structlog for JSON output with redaction and silence uvicorn's access log."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt='iso', utc=True),
            redact_sensitive,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )
    access_logger = logging.getLogger('uvicorn.access')
    access_logger.handlers.clear()
    access_logger.propagate = False
    access_logger.disabled = True
