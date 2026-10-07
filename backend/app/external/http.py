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
from urllib.parse import urlparse

import httpx

from app.external.allowlist import assert_allowed, assert_fulltext_allowed

_USER_AGENT = "ResearchNexus/0.1 (+https://example.invalid/researchnexus)"
_RETRY_AFTER_CAP_S = 60.0


class ExternalError(Exception):
    """Base class for every failure the external layer surfaces to callers."""


class UpstreamUnavailable(ExternalError):
    """A source failed (5xx / timeout / transport error) after all retries.
    `status` is the HTTP status when there was one; `retry_after` is how long
    the source asked callers to wait, when it said."""

    def __init__(self, message: str, *, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class UpstreamRateLimited(ExternalError):
    """A source returned 429 after all retries."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class MalformedUpstreamResponse(ExternalError):
    """A 2xx body could not be parsed into the expected shape."""


class NotAPdf(ExternalError):
    """A full-text link answered with something other than a PDF -- usually a
    publisher's landing or sign-in page."""


class TooLarge(ExternalError):
    """A download went past the size a paper's PDF may have."""


_REDIRECTS = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5


Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]
# (host, outcome, seconds): outcome is "ok", "cached", "rate_limited",
# "http_<status>" or "unreachable" -- one call per request a caller made
OnRequest = Callable[[str, str, float], None]


class ResponseCache:
    """Successful GET bodies by URL, each kept until its expiry. A client
    has its own unless it is handed one to share: discovery shares one across
    runs, so a run started again soon after reuses every answer the last one
    got and asks again only where a source failed."""

    def __init__(self, max_entries: int = 4000) -> None:
        self._entries: dict[str, tuple[float, str]] = {}
        self._max_entries = max_entries

    def get(self, key: str, now: float) -> str | None:
        hit = self._entries.get(key)
        return hit[1] if hit is not None and now < hit[0] else None

    def put(self, key: str, text: str, expires_at: float) -> None:
        self._entries.pop(key, None)
        self._entries[key] = (expires_at, text)
        while len(self._entries) > self._max_entries:
            self._entries.pop(next(iter(self._entries)))  # the oldest entry

    def clear(self) -> None:
        self._entries.clear()


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
        host_headers: dict[str, dict[str, str]] | None = None,
        host_min_interval_s: dict[str, float] | None = None,
        max_retry_wait_s: float = _RETRY_AFTER_CAP_S,
        cache: ResponseCache | None = None,
        on_request: OnRequest | None = None,
    ) -> None:
        self._transport = transport
        # e.g. {"api.semanticscholar.org": {"x-api-key": ...}}: credentials a
        # source accepts, sent only to that host and never part of a cache key
        self._host_headers = host_headers or {}
        # minimum spacing between requests to one host (Semantic Scholar
        # allows about one a second), so parallel strategies queue politely
        # instead of all being rate-limited at once
        self._host_min_interval_s = host_min_interval_s or {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._host_last_sent: dict[str, float] = {}
        # the longest a 429's Retry-After may hold a request up; a caller on a
        # deadline (discovery) sets this low and moves on to other sources
        self._max_retry_wait_s = max_retry_wait_s
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._backoff_base_s = backoff_base_s
        self._cache_ttl_s = cache_ttl_s
        self._sleep: Sleep = sleep or asyncio.sleep
        self._clock: Clock = clock or time.monotonic
        self._cache = cache if cache is not None else ResponseCache()
        # told how every request went, e.g. to show a run's progress per source
        self._on_request = on_request

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
        cached = self._cache.get(key, self._clock())
        if cached is not None:
            self._report(url, "cached", 0.0)
            return cached

        started = time.monotonic()
        try:
            text = await self._send_with_retry(url, params)
        except UpstreamRateLimited:
            self._report(url, "rate_limited", time.monotonic() - started)
            raise
        except UpstreamUnavailable as exc:
            self._report(url, f"http_{exc.status}" if exc.status else "unreachable", time.monotonic() - started)
            raise
        self._report(url, "ok", time.monotonic() - started)
        self._cache.put(key, text, self._clock() + self._cache_ttl_s)
        return text

    def _report(self, url: str, outcome: str, seconds: float) -> None:
        if self._on_request is not None:
            self._on_request((urlparse(url).hostname or "").lower(), outcome, seconds)

    async def _send_with_retry(self, url: str, params: dict[str, Any] | None) -> str:
        last_rate_limit: UpstreamRateLimited | None = None
        async with httpx.AsyncClient(
            transport=self._transport, timeout=self._timeout_s, headers={"User-Agent": _USER_AGENT}
        ) as http:
            for attempt in range(self._max_retries + 1):
                try:
                    await self._throttle(url)
                    resp = await http.get(url, params=params, headers=self._headers_for(url))
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt == self._max_retries:
                        raise UpstreamUnavailable(f"{url}: {type(exc).__name__}") from exc
                    await self._sleep(self._backoff_base_s * (2**attempt))
                    continue

                if resp.status_code == 429:
                    retry_after = parse_retry_after(resp.headers.get("Retry-After"))
                    last_rate_limit = UpstreamRateLimited(f"{url}: rate limited", retry_after)
                    if attempt == self._max_retries or (retry_after or 0) > self._max_retry_wait_s:
                        break
                    await self._sleep(min(retry_after or self._backoff_base_s * (2**attempt), self._max_retry_wait_s))
                    continue

                if resp.status_code >= 500:
                    retry_after = parse_retry_after(resp.headers.get("Retry-After"))
                    # a source that asks for a longer pause than this caller can
                    # wait is not asked again now: that would only be refused too
                    if attempt == self._max_retries or (retry_after or 0) > self._max_retry_wait_s:
                        raise UpstreamUnavailable(
                            f"{url}: HTTP {resp.status_code}", status=resp.status_code, retry_after=retry_after
                        )
                    await self._sleep(retry_after if retry_after is not None else self._backoff_base_s * (2**attempt))
                    continue

                if resp.status_code >= 400:
                    raise UpstreamUnavailable(f"{url}: HTTP {resp.status_code}", status=resp.status_code)

                return resp.text

        assert last_rate_limit is not None
        raise last_rate_limit

    def _headers_for(self, url: str) -> dict[str, str]:
        return self._host_headers.get((urlparse(url).hostname or "").lower(), {})

    async def _throttle(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        interval = self._host_min_interval_s.get(host)
        if not interval:
            return
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._host_last_sent.get(host)
            if last is not None:
                wait = last + interval - self._clock()
                if wait > 0:
                    await self._sleep(wait)
            self._host_last_sent[host] = self._clock()

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
                    await self._throttle(url)
                    resp = await http.get(url, params=params, headers=self._headers_for(url))
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    if attempt == self._max_retries:
                        raise UpstreamUnavailable(f"{url}: {type(exc).__name__}") from exc
                    await self._sleep(self._backoff_base_s * (2**attempt))
                    continue
                if resp.status_code == 429 and attempt < self._max_retries:
                    retry_after = parse_retry_after(resp.headers.get("Retry-After"))
                    if (retry_after or 0) > self._max_retry_wait_s:
                        return resp
                    await self._sleep(min(retry_after or self._backoff_base_s * (2**attempt), self._max_retry_wait_s))
                    continue
                if resp.status_code >= 500:
                    if attempt == self._max_retries:
                        raise UpstreamUnavailable(f"{url}: HTTP {resp.status_code}")
                    await self._sleep(self._backoff_base_s * (2**attempt))
                    continue
                return resp
        raise UpstreamUnavailable(f"{url}: retries exhausted")  # pragma: no cover


    async def get_pdf(self, url: str, *, max_bytes: int) -> tuple[bytes, str]:
        """A paper's PDF from an open-access source (remediation Phase 7), and
        the URL it finally came from. Redirects are followed one hop at a
        time, each hop checked against the full-text source list -- a DOI
        that resolves somewhere else is refused, not followed -- and the body
        is read no further than `max_bytes`. Not retried: the caller tries
        its next source instead."""
        current = url
        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=self._timeout_s,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/pdf,*/*;q=0.5"},
            follow_redirects=False,
        ) as http:
            for _hop in range(_MAX_REDIRECTS + 1):
                # every hop is checked; names are resolved only when the real network is used
                assert_fulltext_allowed(current, resolve=self._transport is None)
                await self._throttle(current)
                try:
                    async with http.stream("GET", current) as resp:
                        if resp.status_code in _REDIRECTS:
                            location = resp.headers.get("location")
                            if not location:
                                raise UpstreamUnavailable(f"{current}: redirect without a location")
                            current = str(httpx.URL(current).join(location))
                            continue
                        if resp.status_code == 429:
                            raise UpstreamRateLimited(f"{current}: rate limited", parse_retry_after(resp.headers.get("Retry-After")))
                        if resp.status_code >= 400:
                            raise UpstreamUnavailable(f"{current}: HTTP {resp.status_code}")
                        declared = resp.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) > max_bytes:
                            raise TooLarge(f"{current}: {int(declared)} bytes")
                        body = bytearray()
                        async for piece in resp.aiter_bytes():
                            body += piece
                            if len(body) > max_bytes:
                                raise TooLarge(f"{current}: over {max_bytes} bytes")
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    raise UpstreamUnavailable(f"{current}: {type(exc).__name__}") from exc
                data = bytes(body)
                # a PDF may carry a few bytes of junk before its header
                if b"%PDF-" not in data[:1024]:
                    raise NotAPdf(f"{current}: {resp.headers.get('content-type', 'no content type')}")
                return data, current
        raise UpstreamUnavailable(f"{url}: more than {_MAX_REDIRECTS} redirects")


def parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None
