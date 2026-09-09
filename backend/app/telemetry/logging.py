"""Structured JSON logging with secret redaction (Roadmap Task 1 item 7).

Anything key-shaped -- field names like api_key/authorization/token/secret,
or a bare "Bearer ..." string value -- is stripped by a processor that runs
before rendering, never trusted to call sites to remember (Architecture §7:
"no secrets in logs"; Data Model §13: "plaintext never stored/logged").
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
    "secret",
    "key_ciphertext",
    "password",
    "jwt_secret",
    "key_vault_secret",
}
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)


def _redact_secrets(_logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]) -> Mapping[str, Any]:
    for field in list(event_dict):
        if field.lower() in _KEY_SHAPED_FIELD_NAMES:
            event_dict[field] = _REDACTED
    for field, value in event_dict.items():
        if isinstance(value, str) and _BEARER_RE.search(value):
            event_dict[field] = _BEARER_RE.sub(f"Bearer {_REDACTED}", value)
    return event_dict


def configure_logging(*, stream: TextIO | None = None) -> None:
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            _redact_secrets,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO
        cache_logger_on_first_use=False,
    )


def get_logger(name: str) -> Any:
    return structlog.get_logger(name)
