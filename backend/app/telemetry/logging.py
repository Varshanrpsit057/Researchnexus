"""Structured JSON logging with secret redaction (Roadmap Task 1 item 7).

Anything key-shaped -- field names like api_key/authorization/token/secret/
password/otp/cookie, or a bare "Bearer ..." string value -- is stripped by a
processor that runs before rendering, never trusted to call sites to
remember (Architecture §7: "no secrets in logs"; Data Model §13:
"plaintext never stored/logged"). Every line of a request carries its
request id (bound by app/middleware.py).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, TextIO

import structlog

_REDACTED = "[REDACTED]"
_KEY_SHAPED_FIELD_NAMES = {
    "api_key",
    "apikey",
    "authorization",
    "token",
    "session_token",
    "secret",
    "secret_key",
    "key_ciphertext",
    "password",
    "password_hash",
    "new_password",
    "current_password",
    "smtp_password",
    "jwt_secret",
    "key_vault_secret",
    "otp",
    "code",
    "cookie",
    "set_cookie",
    "csrf",
    "x_csrf_token",
}
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)
_LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40}


def _redact_secrets(_logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
    for field in list(event_dict):
        if field.lower().replace("-", "_") in _KEY_SHAPED_FIELD_NAMES:
            event_dict[field] = _REDACTED
    for field, value in event_dict.items():
        if isinstance(value, str) and _BEARER_RE.search(value):
            event_dict[field] = _BEARER_RE.sub(f"Bearer {_REDACTED}", value)
    return event_dict


def configure_logging(*, stream: TextIO | None = None, level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            _redact_secrets,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        wrapper_class=structlog.make_filtering_bound_logger(_LEVELS.get(level.upper(), 20)),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
