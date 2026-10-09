"""Request middleware (pure ASGI, so streamed answers -- chat -- pass through
untouched):

- a request id on every request (the caller's X-Request-ID when it is a
  sane token, else a new one), echoed in the response and bound to every
  log line the request writes;
- one access-log line per request: method, route, status, milliseconds,
  and the signed-in user's id (never a cookie, header or body);
- an uncaught error becomes a JSON 500 naming the request id, and its
  traceback is logged under that id;
- state-changing requests from a browser page on another origin are
  refused (the CSRF header check in app/deps.py is the second line);
- request bodies are capped: PDF uploads at the configured PDF size, all
  else at `max_json_body_kb` -- checked against Content-Length first, and
  counted as the body arrives for a body without one;
- security headers on every response.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import urlsplit

import structlog
from fastapi import HTTPException
from starlette.datastructures import Headers, MutableHeaders

from app.config import Settings
from app.telemetry.logging import get_logger

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_log = get_logger("app.http")

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
_UPLOAD_PATH = re.compile(r"^/api/v1/papers/(upload|[^/]+/pdf)$")
# probes that would otherwise fill the log every few seconds
_QUIET_PATHS = frozenset({"/health", "/health/live", "/health/ready"})


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}".lower()


async def _send_json(send: Send, status: int, body: dict[str, Any], headers: list[tuple[bytes, bytes]] | None = None) -> None:
    payload = json.dumps(body).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()), *(headers or [])],
        }
    )
    await send({"type": "http.response.body", "body": payload})


class _BodyTooLarge(HTTPException):
    """Raised while a body is read. An HTTPException, so FastAPI's body
    parsing passes it on as a 413 rather than "error parsing the body"."""

    def __init__(self, limit: int) -> None:
        super().__init__(status_code=413, detail={"error": {"code": "file_too_large", "message": _too_large_message(limit)}})
        self.limit = limit


def _too_large_message(limit: int) -> str:
    mb = limit / (1024 * 1024)
    size = f"{mb:.0f} MB" if mb >= 1 else f"{limit // 1024} KB"
    return f"That's too large: the limit is {size}."


class RequestMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.allowed_origins = {_origin(o) for o in [*settings.cors_allowed_origins, settings.public_app_url]}
        self.upload_limit = settings.max_pdf_mb * 1024 * 1024 + 256 * 1024  # the multipart wrapping
        self.json_limit = settings.max_json_body_kb * 1024
        self.hsts = not settings.is_local and settings.secure_cookies

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        method: str = scope["method"]
        path: str = scope["path"]
        started = time.perf_counter()
        status = 500
        response_started = False
        structlog.contextvars.bind_contextvars(request_id=request_id)

        async def send_wrapped(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                out = MutableHeaders(scope=message)
                out["x-request-id"] = request_id
                out.setdefault("x-content-type-options", "nosniff")
                out.setdefault("x-frame-options", "DENY")
                out.setdefault("referrer-policy", "no-referrer")
                if path.startswith("/api/"):
                    out.setdefault("content-security-policy", "default-src 'none'; frame-ancestors 'none'")
                if path.startswith(("/api/v1/auth", "/api/v1/me")):
                    out["cache-control"] = "no-store"
                if self.hsts:
                    out.setdefault("strict-transport-security", "max-age=31536000; includeSubDomains")
            await send(message)

        try:
            if method not in _SAFE_METHODS:
                origin = headers.get("origin")
                if origin and origin != "null" and _origin(origin) not in self.allowed_origins:
                    _log.warning("request_refused_origin", method=method, path=path)
                    await _send_json(
                        send_wrapped, 403, {"detail": {"error": {"code": "bad_origin", "message": "Requests from this site aren't accepted."}}}
                    )
                    return
                limit = self.upload_limit if _UPLOAD_PATH.match(path) else self.json_limit
                declared = headers.get("content-length")
                if declared is not None and declared.isdigit() and int(declared) > limit:
                    await self._too_large(send_wrapped, limit)
                    return
                receive = self._counting(receive, limit)
            await self.app(scope, receive, send_wrapped)
        except _BodyTooLarge as e:
            if not response_started:
                await self._too_large(send_wrapped, e.limit)
        except Exception:
            _log.exception("unhandled_error", method=method, path=path)
            if not response_started:
                await _send_json(
                    send_wrapped,
                    500,
                    {"detail": {"error": {"code": "internal_error", "message": "Something went wrong on our side. Try again.", "request_id": request_id}}},
                )
            else:
                raise
        finally:
            route = scope.get("route")
            fields = {
                "method": method,
                "route": getattr(route, "path", None) or ("unmatched" if status == 404 else path),
                "status": status,
                "ms": round((time.perf_counter() - started) * 1000, 1),
            }
            if state.get("user_id"):
                fields["user_id"] = state["user_id"]
            if path in _QUIET_PATHS and status < 500:
                _log.debug("http_request", **fields)
            elif status >= 500:
                _log.error("http_request", **fields)
            else:
                _log.info("http_request", **fields)
            structlog.contextvars.unbind_contextvars("request_id")

    @staticmethod
    def _counting(receive: Receive, limit: int) -> Receive:
        seen = 0

        async def counted() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    raise _BodyTooLarge(limit)
            return message

        return counted

    @staticmethod
    async def _too_large(send: Send, limit: int) -> None:
        await _send_json(send, 413, {"detail": {"error": {"code": "file_too_large", "message": _too_large_message(limit)}}})
