from __future__ import annotations

import asyncio

import httpx
import pytest

from app.external.allowlist import DisallowedHost
from app.external.http import (
    ExternalHttpClient,
    MalformedUpstreamResponse,
    UpstreamRateLimited,
    UpstreamUnavailable,
)

_URL = "https://api.openalex.org/works"


def _client(handler: httpx.MockTransport, **kw: object) -> ExternalHttpClient:
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    client = ExternalHttpClient(
        transport=handler,
        timeout_s=1.0,
        max_retries=kw.get("max_retries", 3),  # type: ignore[arg-type]
        backoff_base_s=kw.get("backoff_base_s", 0.5),  # type: ignore[arg-type]
        cache_ttl_s=kw.get("cache_ttl_s", 300.0),  # type: ignore[arg-type]
        sleep=_fake_sleep,
    )
    client._test_sleeps = sleeps  # type: ignore[attr-defined]
    return client


def test_get_json_happy_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": [{"id": "W1"}]})

    client = _client(httpx.MockTransport(handler))
    body = asyncio.run(client.get_json(_URL, params={"search": "rag"}))
    assert body == {"results": [{"id": "W1"}]}


def test_get_text_happy_path() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<feed>ok</feed>")

    client = _client(httpx.MockTransport(handler))
    assert asyncio.run(client.get_text("https://export.arxiv.org/api/query")) == "<feed>ok</feed>"


def test_malformed_json_raises_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="{not json")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(MalformedUpstreamResponse):
        asyncio.run(client.get_json(_URL))


def test_5xx_is_retried_then_raises_upstream_unavailable() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    client = _client(httpx.MockTransport(handler), max_retries=3)
    with pytest.raises(UpstreamUnavailable):
        asyncio.run(client.get_json(_URL))
    assert calls["n"] == 4  # initial + 3 retries
    assert len(client._test_sleeps) == 3  # type: ignore[attr-defined]


def test_5xx_then_success_recovers() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"ok": True})

    client = _client(httpx.MockTransport(handler))
    assert asyncio.run(client.get_json(_URL)) == {"ok": True}
    assert calls["n"] == 2


def test_429_honours_retry_after_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")
        return httpx.Response(200, json={"ok": True})

    client = _client(httpx.MockTransport(handler))
    assert asyncio.run(client.get_json(_URL)) == {"ok": True}
    assert client._test_sleeps == [7.0]  # type: ignore[attr-defined]


def test_429_exhausted_raises_rate_limited_with_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "3"}, text="nope")

    client = _client(httpx.MockTransport(handler), max_retries=2)
    with pytest.raises(UpstreamRateLimited) as excinfo:
        asyncio.run(client.get_json(_URL))
    assert excinfo.value.retry_after == 3.0


def test_timeout_is_retried_then_raises_upstream_unavailable() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        raise httpx.ConnectTimeout("timed out")

    client = _client(httpx.MockTransport(handler), max_retries=2)
    with pytest.raises(UpstreamUnavailable):
        asyncio.run(client.get_json(_URL))
    assert calls["n"] == 3


def test_successful_response_is_cached_and_not_refetched() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"n": calls["n"]})

    client = _client(httpx.MockTransport(handler))
    first = asyncio.run(client.get_json(_URL, params={"search": "rag"}))
    second = asyncio.run(client.get_json(_URL, params={"search": "rag"}))
    assert first == second == {"n": 1}
    assert calls["n"] == 1
    # a different query is a different cache key
    asyncio.run(client.get_json(_URL, params={"search": "other"}))
    assert calls["n"] == 2


def test_cache_entry_expires_after_ttl() -> None:
    now = {"t": 1000.0}

    def clock() -> float:
        return now["t"]

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"n": calls["n"]})

    client = ExternalHttpClient(
        transport=httpx.MockTransport(handler), timeout_s=1.0, cache_ttl_s=100.0, clock=clock
    )
    asyncio.run(client.get_json(_URL))
    now["t"] = 1050.0
    asyncio.run(client.get_json(_URL))
    assert calls["n"] == 1  # still cached
    now["t"] = 1200.0
    asyncio.run(client.get_json(_URL))
    assert calls["n"] == 2  # expired -> refetched


def test_disallowed_host_is_rejected_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("request should never be sent to a disallowed host")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(DisallowedHost):
        asyncio.run(client.get_json("https://evil.example.com/x"))
