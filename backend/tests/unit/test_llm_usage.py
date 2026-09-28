"""Model-provider usage metering (remediation Phase 2): every call a key makes
is recorded with the provider's own token counts, a failed call with its
kind of failure, and a rejected key stops being the working key."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.domain.usage import LlmCall
from app.domain.user import ApiKeyStatus, LlmProvider
from app.llm.client import ChatMessage, LlmProviderError
from app.llm.providers.gemini import GeminiClient
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import resolve_llm_session
from app.llm.usage import (
    MeteredClient,
    current_scope,
    db_recorder,
    usage_scope,
    usage_scope_default,
    usage_tally,
)
from app.security.key_vault import KeyVault

PING = [ChatMessage(role="user", content="ping")]


@pytest.fixture()
def db(tmp_path) -> Iterator[Session]:  # noqa: ANN001
    engine = create_engine(f"sqlite:///{tmp_path / 'usage.db'}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _adapter(handler) -> OpenAiCompatClient:  # noqa: ANN001
    return OpenAiCompatClient(LlmProvider.DEEPSEEK, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "deepseek-flash",
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "prompt_cache_hit_tokens": 64},
        },
    )


def test_scopes_nest_and_a_default_scope_never_overrides_the_callers() -> None:
    assert current_scope().feature == "other"
    with usage_scope("gaps", workspace_id="ws_1", job_id="job_1"):
        with usage_scope_default("profile"):
            assert (current_scope().feature, current_scope().workspace_id) == ("gaps", "ws_1")
        with usage_scope("chat", workspace_id="ws_2"):
            assert current_scope().feature == "chat"
        assert current_scope().job_id == "job_1"
    with usage_scope_default("profile"):
        assert current_scope().feature == "profile"
    assert current_scope().feature == "other"


def test_a_call_is_recorded_with_the_providers_usage_and_where_it_was_made() -> None:
    calls: list[LlmCall] = []
    client = MeteredClient(_adapter(_ok), owner_id="usr_1", provider=LlmProvider.DEEPSEEK, recorder=calls.append)

    async def ask() -> None:
        with usage_scope("chat", workspace_id="ws_1"):
            await client.chat(api_key="sk-x", model="deepseek-chat", messages=PING, json_mode=True)

    asyncio.run(ask())
    [call] = calls
    assert (call.owner_id, call.feature, call.workspace_id, call.provider) == ("usr_1", "chat", "ws_1", "deepseek")
    assert call.model == "deepseek-flash"  # the model that answered, not the alias asked for
    assert (call.prompt_tokens, call.completion_tokens, call.cached_prompt_tokens) == (120, 30, 64)
    assert call.ok and call.error_kind is None


def test_a_failed_call_is_recorded_with_its_kind_and_still_raised() -> None:
    calls: list[LlmCall] = []
    client = MeteredClient(
        _adapter(lambda r: httpx.Response(402, json={"error": {"message": "Insufficient Balance"}})),
        owner_id="usr_1",
        provider=LlmProvider.DEEPSEEK,
        recorder=calls.append,
    )
    with pytest.raises(LlmProviderError):
        asyncio.run(client.chat(api_key="sk-x", model="deepseek-flash", messages=PING))
    assert [(c.ok, c.error_kind, c.prompt_tokens) for c in calls] == [(False, "insufficient_balance", 0)]


def test_structured_output_records_the_first_reply_and_its_repair() -> None:
    class Out(BaseModel):
        ok: bool

    replies = iter(["not json", '{"ok": true}'])
    calls: list[LlmCall] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": next(replies)}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})

    client = MeteredClient(_adapter(handler), owner_id="usr_1", provider=LlmProvider.DEEPSEEK, recorder=calls.append)
    assert asyncio.run(client.structured(api_key="sk-x", model="m", messages=PING, schema=Out)).ok is True
    assert len(calls) == 2 and sum(c.prompt_tokens for c in calls) == 10


def test_recording_that_fails_never_breaks_the_call() -> None:
    def broken(_call: LlmCall) -> None:
        raise RuntimeError("database is locked")

    client = MeteredClient(_adapter(_ok), owner_id="usr_1", provider=LlmProvider.DEEPSEEK, recorder=db_recorder(create_engine("sqlite://")))
    # a recorder whose table doesn't exist: logged, not raised
    assert asyncio.run(client.chat(api_key="sk-x", model="m", messages=PING)).content == '{"ok": true}'
    with pytest.raises(RuntimeError):
        # a recorder the caller wrote badly does raise -- db_recorder is the one that must not
        asyncio.run(MeteredClient(_adapter(_ok), owner_id="u", provider=LlmProvider.DEEPSEEK, recorder=broken).chat(api_key="k", model="m", messages=PING))


def _user_with_key(db: Session, settings: Settings) -> str:
    user = repo.create_user(db, user_id="usr_1", email="r@example.com")
    repo.upsert_api_key(
        db, new_key_id="key_1", owner_id=user.id, provider=LlmProvider.DEEPSEEK,
        key_ciphertext=KeyVault(settings.key_vault_secret).encrypt("sk-test-0000"), key_last4="0000",
        status=ApiKeyStatus.WORKING, checked_at=datetime.now(timezone.utc),
    )
    return user.id


def test_a_resolved_session_is_metered_into_the_database_and_a_rejected_key_stops_working(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.llm.session as session_module

    settings = Settings(_env_file=None, key_vault_secret=Fernet.generate_key().decode())  # type: ignore[call-arg]
    user_id = _user_with_key(db, settings)
    user = repo.get_user(db, user_id)
    assert user is not None

    monkeypatch.setattr(session_module, "get_llm_client", lambda provider: _adapter(_ok))
    session = resolve_llm_session(db, user, settings)
    assert session is not None and session.model == "deepseek-flash"
    with usage_scope("compare", workspace_id="ws_9"):
        asyncio.run(session.client.chat(api_key=session.api_key, model=session.model, messages=PING))
    [call] = repo.list_llm_calls(db, user_id)
    assert (call.feature, call.workspace_id, call.prompt_tokens) == ("compare", "ws_9", 120)
    assert repo.list_llm_calls(db, user_id, workspace_id="ws_9") == [call]

    rejected = lambda r: httpx.Response(401, json={"error": {"message": "Authentication Fails"}})  # noqa: E731
    monkeypatch.setattr(session_module, "get_llm_client", lambda provider: _adapter(rejected))
    session = resolve_llm_session(db, user, settings)
    assert session is not None
    with pytest.raises(LlmProviderError):
        asyncio.run(session.client.chat(api_key=session.api_key, model=session.model, messages=PING))
    db.expire_all()
    assert [k.status for k in repo.list_api_keys(db, user_id)] == [ApiKeyStatus.FAILED]
    assert resolve_llm_session(db, user, settings) is None  # the next call says no key works
    assert [c.error_kind for c in repo.list_llm_calls(db, user_id)] == [None, "auth"]


def test_a_model_override_names_the_model_a_provider_is_asked_for(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.llm.session as session_module

    settings = Settings(_env_file=None, key_vault_secret=Fernet.generate_key().decode(), llm_models={"deepseek": "deepseek-v4-pro"})  # type: ignore[call-arg]
    user_id = _user_with_key(db, settings)
    user = repo.get_user(db, user_id)
    assert user is not None
    monkeypatch.setattr(session_module, "get_llm_client", lambda provider: _adapter(_ok))
    session = resolve_llm_session(db, user, settings)
    assert session is not None and session.model == "deepseek-v4-pro"


def test_a_key_saved_under_another_vault_secret_is_not_a_usable_session(db: Session) -> None:
    settings = Settings(_env_file=None, key_vault_secret=Fernet.generate_key().decode())  # type: ignore[call-arg]
    user_id = _user_with_key(db, settings)
    user = repo.get_user(db, user_id)
    assert user is not None
    rotated = Settings(_env_file=None, key_vault_secret=Fernet.generate_key().decode())  # type: ignore[call-arg]
    assert resolve_llm_session(db, user, rotated) is None


# --- one meaning for every provider's counts (remediation Phase 5) -----------


def test_every_adapter_counts_reasoning_inside_completion_and_cache_inside_prompt() -> None:
    """prompt + completion is the whole call whichever provider answered, so
    usage from different providers can be added up."""

    def deepseek(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "ok"}}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,  # includes the 30 reasoning tokens
                    "prompt_cache_hit_tokens": 60,
                    "completion_tokens_details": {"reasoning_tokens": 30},
                },
            },
        )

    def gemini(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
                # Gemini counts thoughts apart: the reply is 20, the thinking 30
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "cachedContentTokenCount": 60,
                    "candidatesTokenCount": 20,
                    "thoughtsTokenCount": 30,
                    "totalTokenCount": 150,
                },
            },
        )

    async def ask() -> list[tuple[int, int, int, int]]:
        out = []
        for adapter in (_adapter(deepseek), GeminiClient(client=httpx.AsyncClient(transport=httpx.MockTransport(gemini)))):
            r = await adapter.chat(api_key="sk-x", model="m", messages=PING)
            out.append((r.prompt_tokens, r.completion_tokens, r.cached_prompt_tokens, r.reasoning_tokens))
        return out

    ds, gm = asyncio.run(ask())
    assert ds == gm == (100, 50, 60, 30)


def test_a_tally_counts_the_calls_made_inside_it_including_in_tasks_it_starts() -> None:
    calls: list[LlmCall] = []
    client = MeteredClient(_adapter(_ok), owner_id="usr_1", provider=LlmProvider.DEEPSEEK, recorder=calls.append)
    failing = MeteredClient(
        _adapter(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}})),
        owner_id="usr_1",
        provider=LlmProvider.DEEPSEEK,
        recorder=calls.append,
    )

    async def work() -> tuple[object, object]:
        await client.chat(api_key="sk-x", model="m", messages=PING)  # outside every tally
        with usage_tally() as outer:
            await client.chat(api_key="sk-x", model="m", messages=PING)
            with usage_tally() as inner:
                await asyncio.gather(*(client.chat(api_key="sk-x", model="m", messages=PING) for _ in range(2)))
                with pytest.raises(LlmProviderError):
                    await failing.chat(api_key="sk-x", model="m", messages=PING)
        return outer, inner

    outer, inner = asyncio.run(work())
    assert len(calls) == 5  # the ledger has every call; each tally only its own
    assert (inner.calls, inner.failed_calls, inner.prompt_tokens, inner.completion_tokens, inner.cached_prompt_tokens) == (3, 1, 240, 60, 128)  # type: ignore[attr-defined]
    assert (outer.calls, outer.prompt_tokens, outer.completion_tokens) == (4, 360, 90)  # type: ignore[attr-defined]

