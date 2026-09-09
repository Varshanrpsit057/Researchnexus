"""Shared resilient HTTP layer for app/external/* (Architecture §1.1 row H:
"behind a uniform interface with allowlist + retry + rate-limit + cache").

- every URL passes app.external.allowlist.assert_allowed first (SSRF);
- transient failures (5xx, connect/read timeouts, transport errors) are
  retried with exponential backoff up to `max_retries`, then surface as a
  typed `UpstreamUnavailable` -- callers never see a raw httpx error;
- HTTP 429 honours `Retry-After` and, once retries are exhausted, raises
  `UpstreamRateLimited` carrying the server's hint;
- a non-JSON body where JSON is expected raises `MalformedUpstreamResponse`
  (Roadmap Phase 4 Tests: "malformed responses");
- successful GETs are cached in-process with a TTL ("cache aggressively" --
  Roadmap Phase 4 risks); no new dependency, just a dict + a monotonic
  clock.

Retry is a small hand-rolled loop rather than a `tenacity` dependency --
the policy here is a dozen lines and fully covered by tests.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.external.allowlist import assert_allowed

_USER_AGENT = "ResearchNexus/0.1 (+https://example.invalid/researchnexus)"
_RETRY_AFTER_CAP_S = 60.0


class ExternalError(Exception):
    """Base class for every failure the external layer surfaces to callers."""


class UpstreamUnavailable(ExternalError):
    """A source failed (5xx / timeout / transport error) after all retries."""


class UpstreamRateLimited(ExternalError):
    """A source returned 429 after all retries."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MalformedUpstreamResponse(ExternalError):
    """A 2xx body could not be parsed into the expected shape."""


Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class ExternalHttpClient:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_s: float = 15.0,
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        cache_ttl_s: float = 300.0,
        sleep: Sleep | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._transport = transport
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._cache_ttl_s = cache_ttl_s
        self._sleep: Sleep = sleep or asyncio.sleep
        self._clock: Clock = clock or time.monotonic
        self._cache: dict[str, tuple[float, str]] = {}

    # -- cache ---------------------------------------------------------------

    @staticmethod
    def _cache_key(url: str, params: dict[str, Any] | None) -> str:
        if not params:
            return url
        rendered = "&".join(f"{k}={params[k]}" for k in sorted(params))
        return f"{url}?{rendered}"

    def clear_cache(self) -> None:
        self._cache.clear()

    # -- request ----------------------------------------------------------------

    async def _request_text(self, url: str, params: dict[str, Any] | None) -> str:
        assert_allowed(url)
        key = self._cache_key(url, params)
        cached = self._cache.get(key)
        if cached is not None and self._clock() < cached[0]:
            return cached[1]

        text = await self._send_with_retry(url, params)
        self._cache[key] = (self._clock() + self._cache_ttl_s, text)
        return text

    async def _send_with_retry(self, url: str, params: dict[str, Any] | None) -> str:
        last_rate_limit: UpstreamRateLimited | None = None
        async with httpx.AsyncClient(
            transport=self._transport, timeout=self._timeout_s, headers={"User-Agent": _USER_AGENT}
        ) as http:
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await http.get(url, params=params)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt == self._max_retries:
                        raise UpstreamUnavailable(f"{url}: {type(exc).__name__}") from exc
                    await self._sleep(self._backoff_base_s * (2**attempt))
                    continue

                if resp.status_code == 429:
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    last_rate_limit = UpstreamRateLimited(f"{url}: rate limited", retry_after)
                    if attempt == self._max_retries:
                        break
                    await self._sleep(min(retry_after or self._backoff_base_s * (2**attempt), _RETRY_AFTER_CAP_S))
                    continue

                if resp.status_code >= 500:
                    if attempt == self._max_retries:
                        raise UpstreamUnavailable(f"{url}: HTTP {resp.status_code}")
                    await self._sleep(self._backoff_base_s * (2**attempt))
                    continue

                if resp.status_code >= 400:
                    raise UpstreamUnavailable(f"{url}: HTTP {resp.status_code}")

                return resp.text

        assert last_rate_limit is not None
        raise last_rate_limit

    # -- public -----------------------------------------------------------------

    async def get_text(self, url: str, params: dict[str, Any] | None = None) -> str:
        return await self._request_text(url, params)

    async def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        text = await self._request_text(url, params)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise MalformedUpstreamResponse(f"{url}: response was not valid JSON") from exc

    async def get_response(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """For callers that must inspect a non-2xx status themselves (e.g.
        Crossref returning 404 for an unknown DOI). Retry/allowlist still
        apply; 404 is returned, not raised."""
        assert_allowed(url)
        async with httpx.AsyncClient(
            transport=self._transport, timeout=self._timeout_s, headers={"User-Agent": _USER_AGENT}
        ) as http:
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await http.get(url, params=params)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt == self._max_retries:
                        raise UpstreamUnavailable(f"{url}: {type(exc).__name__}") from exc
                    await self._sleep(self._backoff_base_s * (2**attempt))
                    continue
                if resp.status_code >= 500:
                    if attempt == self._max_retries:
                        raise UpstreamUnavailable(f"{url}: HTTP {resp.status_code}")
                    await self._sleep(self._backoff_base_s * (2**attempt))
                    continue
                return resp
        raise UpstreamUnavailable(f"{url}: retries exhausted")  # pragma: no cover


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
