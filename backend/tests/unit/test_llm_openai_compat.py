"""The OpenAI-compatible adapter against DeepSeek-shaped replies (remediation
Phase 2): the request it sends, the usage it reads, and what every kind of
failure becomes. The provider is a mock transport; the shapes are the ones
DeepSeek really sends (checked live against api.deepseek.com)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator

import httpx
import pytest

from app.domain.user import LlmProvider
from app.llm.client import ChatMessage, LlmErrorKind, LlmProviderError, describe_provider_error
from app.llm.providers.openai_compat import DEFAULT_MODELS, OpenAiCompatClient

MESSAGES = [ChatMessage(role="user", content="Return JSON please")]

DEEPSEEK_USAGE = {
    "prompt_tokens": 870,
    "completion_tokens": 183,
    "total_tokens": 1053,
    "prompt_tokens_details": {"cached_tokens": 640},
    "prompt_cache_hit_tokens": 640,
    "prompt_cache_miss_tokens": 230,
}


def _ok(content: str = '{"a": 1}', usage: dict | None = None, model: str = "deepseek-flash") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": usage if usage is not None else DEEPSEEK_USAGE,
        },
    )


@pytest.fixture(autouse=True)
def _fresh_replacements() -> Iterator[None]:
    OpenAiCompatClient._replaced.clear()
    yield
    OpenAiCompatClient._replaced.clear()


def _client(handler: Callable[[httpx.Request], httpx.Response], provider: LlmProvider = LlmProvider.DEEPSEEK, **kw: object) -> OpenAiCompatClient:
    return OpenAiCompatClient(provider, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), **kw)  # type: ignore[arg-type]


def _chat(client: OpenAiCompatClient, **kw: object):  # noqa: ANN202
    return asyncio.run(client.chat(api_key="sk-live-abcdef123456", model=kw.pop("model", DEFAULT_MODELS[LlmProvider.DEEPSEEK]), messages=MESSAGES, **kw))  # type: ignore[arg-type]


def _raises(client: OpenAiCompatClient, **kw: object) -> LlmProviderError:
    with pytest.raises(LlmProviderError) as info:
        _chat(client, **kw)
    return info.value


# --- the request and the reply ------------------------------------------------


def test_deepseek_is_called_at_its_documented_url_with_its_current_model_and_json_mode() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _ok()

    result = _chat(_client(handler), json_mode=True)
    request = seen[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-live-abcdef123456"
    assert body["model"] == "deepseek-flash"  # "deepseek-chat" is only a legacy alias of it
    assert body["thinking"] == {"type": "disabled"}  # it thinks by default: slow, costly, no better here
    assert body["response_format"] == {"type": "json_object"}
    assert "stream" not in body
    assert result.content == '{"a": 1}' and result.finish_reason == "stop" and result.model == "deepseek-flash"


def test_usage_is_the_providers_own_count_with_cache_hits_and_reasoning() -> None:
    deepseek = _chat(_client(lambda r: _ok()))
    assert (deepseek.prompt_tokens, deepseek.completion_tokens, deepseek.cached_prompt_tokens) == (870, 183, 640)

    openai_usage = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 64},
        "completion_tokens_details": {"reasoning_tokens": 30},
    }
    openai = _chat(_client(lambda r: _ok(usage=openai_usage, model="gpt-4o-mini"), LlmProvider.OPENAI), model="gpt-4o-mini")
    assert (openai.cached_prompt_tokens, openai.reasoning_tokens, openai.model) == (64, 30, "gpt-4o-mini")

    bare = _chat(_client(lambda r: httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})))
    assert (bare.prompt_tokens, bare.completion_tokens) == (0, 0)


def test_a_provider_that_refuses_json_mode_is_asked_again_without_it_and_not_asked_twice() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format is not supported by this model"}})
        return _ok()

    client = _client(handler, LlmProvider.TOGETHER)
    _chat(client, json_mode=True, model="m")
    _chat(client, json_mode=True, model="m")
    assert ["response_format" in b for b in bodies] == [True, False, False]


def test_only_deepseek_is_asked_not_to_think_and_a_refusal_drops_the_flag_once() -> None:
    groq: list[dict] = []

    def record(request: httpx.Request) -> httpx.Response:
        groq.append(json.loads(request.content))
        return _ok()

    _chat(_client(record, LlmProvider.GROQ), model="m")
    assert "thinking" not in groq[0]

    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "thinking" in body:
            return httpx.Response(400, json={"error": {"message": "Unknown parameter: thinking"}})
        return _ok()

    client = _client(handler)
    _chat(client)
    _chat(client)
    assert ["thinking" in b for b in bodies] == [True, False, False]


# --- failures ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "payload", "kind"),
    [
        (401, {"error": {"message": "Authentication Fails, Your api key: ****3456 is invalid", "type": "authentication_error"}}, LlmErrorKind.AUTH),
        (403, {"error": {"message": "forbidden"}}, LlmErrorKind.AUTH),
        (402, {"error": {"message": "Insufficient Balance", "type": "unknown_error"}}, LlmErrorKind.INSUFFICIENT_BALANCE),
        (429, {"error": {"message": "You exceeded your current quota", "code": "insufficient_quota"}}, LlmErrorKind.INSUFFICIENT_BALANCE),
        (400, {"error": {"message": "Invalid request: messages must not be empty"}}, LlmErrorKind.BAD_REQUEST),
        (422, {"error": {"message": "Invalid Parameters"}}, LlmErrorKind.BAD_REQUEST),
    ],
)
def test_a_failure_the_person_must_fix_is_named_and_not_retried(status: int, payload: dict, kind: LlmErrorKind) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, json=payload)

    error = _raises(_client(handler))
    assert (error.kind, error.status, error.provider) == (kind, status, "deepseek")
    assert len(calls) == 1


def test_rate_limiting_is_retried_after_the_wait_the_provider_asks_for() -> None:
    waits: list[float] = []
    replies = iter([httpx.Response(429, headers={"retry-after": "3"}, json={"error": {"message": "slow down"}}), _ok()])

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    result = _chat(_client(lambda r: next(replies), sleep=sleep))
    assert result.content == '{"a": 1}' and waits == [3.0]


def test_an_unavailable_server_is_retried_twice_with_backoff_then_named() -> None:
    waits: list[float] = []
    calls = []

    async def sleep(seconds: float) -> None:
        waits.append(seconds)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"error": {"message": "Server overloaded"}})

    error = _raises(_client(handler, sleep=sleep))
    assert error.kind is LlmErrorKind.UNAVAILABLE and len(calls) == 3 and waits == [1.0, 2.0]


def test_transport_failures_become_provider_errors_never_raw_httpx() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert _raises(_client(timeout)).kind is LlmErrorKind.TIMEOUT
    connect = _raises(_client(refused))
    assert connect.kind is LlmErrorKind.UNAVAILABLE and connect.retryable


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>bad gateway</html>"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {"content": None}, "finish_reason": "length"}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": "   "}}]}),
        httpx.Response(200, json=["not", "an", "object"]),
    ],
)
def test_a_reply_that_is_not_a_readable_completion_is_a_bad_response(response: httpx.Response) -> None:
    assert _raises(_client(lambda r: response)).kind is LlmErrorKind.BAD_RESPONSE


def test_a_key_the_provider_echoes_is_never_passed_on() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key sk-live-abcdef123456 rejected"}})

    error = _raises(_client(handler))
    assert "sk-live" not in str(error) and "sk-live" not in (error.detail or "")


def test_the_message_a_person_sees_names_the_provider_and_what_to_do() -> None:
    def err(kind: LlmErrorKind, detail: str | None = None) -> str:
        return describe_provider_error(LlmProviderError("x", kind=kind, provider="deepseek", detail=detail))

    assert err(LlmErrorKind.AUTH) == "DeepSeek rejected the saved API key. Check it in Settings, or save a new one."
    assert err(LlmErrorKind.INSUFFICIENT_BALANCE) == "Your DeepSeek account is out of credit. Top it up, then try again."
    assert err(LlmErrorKind.TIMEOUT) == "DeepSeek took too long to answer. Try again in a moment."
    assert err(LlmErrorKind.BAD_REQUEST, "The supported API model names are deepseek-flash, deepseek-v4-pro.") == (
        "DeepSeek refused the request (The supported API model names are deepseek-flash, deepseek-v4-pro)."
    )


# --- a renamed model ---------------------------------------------------------------


def test_a_model_the_provider_no_longer_offers_is_replaced_by_its_current_one_once() -> None:
    posted: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert str(request.url) == "https://api.deepseek.com/models"
            return httpx.Response(200, json={"object": "list", "data": [{"id": "deepseek-flash"}, {"id": "deepseek-v4-pro"}]})
        model = json.loads(request.content)["model"]
        posted.append(model)
        if model == "deepseek-chat":
            return httpx.Response(
                400, json={"error": {"message": "The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed deepseek-chat."}}
            )
        return _ok()

    client = _client(handler)
    assert _chat(client, model="deepseek-chat").content == '{"a": 1}'
    _chat(client, model="deepseek-chat")  # remembered: no second refusal
    assert posted == ["deepseek-chat", "deepseek-flash", "deepseek-flash"]


# --- streaming ------------------------------------------------------------------------


def _sse(*lines: str) -> httpx.Response:
    return httpx.Response(200, headers={"content-type": "text/event-stream; charset=utf-8"}, content="\n".join(lines).encode())


def test_a_streamed_reply_arrives_piece_by_piece_with_its_usage_at_the_end() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return _sse(
            ": keep-alive",
            "",
            'data: {"model":"deepseek-flash","choices":[{"index":0,"delta":{"role":"assistant","content":""}}]}',
            "",
            'data: {"model":"deepseek-flash","choices":[{"index":0,"delta":{"content":"1, 2"}}]}',
            "",
            ": keep-alive",
            'data: {"model":"deepseek-flash","choices":[{"index":0,"delta":{"content":", 3"},"finish_reason":"stop"}]}',
            "",
            'data: {"model":"deepseek-flash","choices":[],"usage":{"prompt_tokens":15,"completion_tokens":8,"prompt_cache_hit_tokens":0}}',
            "",
            "data: [DONE]",
            "",
        )

    pieces: list[str] = []
    result = _chat(_client(handler), on_delta=pieces.append)
    assert bodies[0]["stream"] is True and bodies[0]["stream_options"] == {"include_usage": True}
    assert pieces == ["1, 2", ", 3"] and result.content == "1, 2, 3"
    assert (result.prompt_tokens, result.completion_tokens, result.finish_reason) == (15, 8, "stop")


def test_a_stream_that_breaks_off_with_an_error_is_a_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _sse('data: {"choices":[{"delta":{"content":"par"}}]}', "", 'data: {"error":{"message":"overloaded"}}', "")

    assert _raises(_client(handler), on_delta=lambda _: None).kind is LlmErrorKind.UNAVAILABLE


def test_a_provider_that_answers_a_stream_request_in_one_piece_still_works() -> None:
    pieces: list[str] = []
    result = _chat(_client(lambda r: _ok("whole")), on_delta=pieces.append)
    assert pieces == ["whole"] and result.content == "whole" and result.prompt_tokens == 870
