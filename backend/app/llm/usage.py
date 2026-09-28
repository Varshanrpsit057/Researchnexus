"""Model-provider usage metering (remediation Phase 2).

Every call a user's key makes goes through `MeteredClient`, which records
one `LlmCall` row with the provider's own token counts -- or, for a failed
call, the kind of failure. That covers what nothing recorded before: turns
that failed and were never saved, and every stage outside chat. The budget
reads real usage from these rows, never from an estimate.

What a call was for comes from the `usage_scope` its caller is running in
(`with usage_scope("chat", workspace_id=...)`); a context variable, so it
follows the work into async tasks without being passed through every
stage. A call outside any scope is recorded as "other".

`usage_tally` counts what one piece of work used while it runs (a stage
run's real tokens, remediation Phase 5), from the same calls the ledger
records -- never from a stage's own estimate.

A rejected key (the provider answered 401/403 on a real call) is marked
failed as it happens, so the next call picks another working key, or says
plainly that none works, instead of failing the same way again.

Recording never breaks the work it measures: it writes in its own short
session, and a failed write is logged, not raised.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import Engine
from sqlalchemy.orm import sessionmaker

from app.db import repository as repo
from app.domain.usage import LlmCall
from app.domain.user import LlmCapabilities, LlmProvider
from app.llm.client import (
    ChatMessage,
    ChatResult,
    DeltaHook,
    LLMClient,
    LlmErrorKind,
    LlmProviderError,
    T,
)
from app.llm.schema_repair import build_repair_messages, parse_structured
from app.telemetry.logging import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class UsageScope:
    feature: str
    workspace_id: str | None = None
    job_id: str | None = None


_scope: ContextVar[UsageScope | None] = ContextVar("llm_usage_scope", default=None)


@contextmanager
def usage_scope(feature: str, *, workspace_id: str | None = None, job_id: str | None = None) -> Iterator[UsageScope]:
    """Calls made inside this block are recorded as `feature` (in
    `workspace_id`, for `job_id`)."""
    scope = UsageScope(feature, workspace_id, job_id)
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


@contextmanager
def usage_scope_default(
    feature: str, *, workspace_id: str | None = None, job_id: str | None = None
) -> Iterator[UsageScope]:
    """`usage_scope`, unless the caller already set one (a gaps run that
    profiles its papers is still the gaps run's usage)."""
    outer = _scope.get()
    if outer is not None:
        yield outer
        return
    with usage_scope(feature, workspace_id=workspace_id, job_id=job_id) as scope:
        yield scope


def current_scope() -> UsageScope:
    return _scope.get() or UsageScope("other")


@dataclass
class UsageTally:
    """What the calls made while it was open used (see `usage_tally`)."""

    calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    reasoning_tokens: int = 0

    def add(self, call: LlmCall) -> None:
        self.calls += 1
        self.failed_calls += 0 if call.ok else 1
        self.prompt_tokens += call.prompt_tokens
        self.completion_tokens += call.completion_tokens
        self.cached_prompt_tokens += call.cached_prompt_tokens
        self.reasoning_tokens += call.reasoning_tokens


_tallies: ContextVar[tuple[UsageTally, ...]] = ContextVar("llm_usage_tallies", default=())


@contextmanager
def usage_tally() -> Iterator[UsageTally]:
    """Counts every call made inside this block, including those in tasks it
    starts; tallies nest (a stage inside a job counts toward both)."""
    tally = UsageTally()
    token = _tallies.set((*_tallies.get(), tally))
    try:
        yield tally
    finally:
        _tallies.reset(token)


Recorder = Callable[[LlmCall], None]


def db_recorder(engine: Engine) -> Recorder:
    """Records into the caller's database, each call in its own short
    session: usage is kept even when the work it was part of fails."""
    factory = sessionmaker(bind=engine, autoflush=False)

    def record(call: LlmCall) -> None:
        db = factory()
        try:
            repo.record_llm_call(db, call)
            if call.error_kind == LlmErrorKind.AUTH.value:
                repo.mark_api_key_failed(db, call.owner_id, LlmProvider(call.provider))
        except Exception:  # noqa: BLE001 - usage recording must never break the call it measures
            _log.exception("llm_usage_not_recorded", provider=call.provider, feature=call.feature)
            db.rollback()
        finally:
            db.close()

    return record


class MeteredClient:
    """A provider adapter whose every call is recorded (see module docstring)."""

    def __init__(self, inner: LLMClient, *, owner_id: str, provider: LlmProvider, recorder: Recorder) -> None:
        self._inner = inner
        self._owner_id = owner_id
        self._provider = provider
        self._record = recorder

    def _note(self, call: LlmCall) -> None:
        for tally in _tallies.get():
            tally.add(call)
        self._record(call)

    def _call(self, scope: UsageScope, model: str, started: float, **fields: object) -> LlmCall:
        return LlmCall(
            id=f"llm_{uuid.uuid4().hex[:20]}",
            owner_id=self._owner_id,
            workspace_id=scope.workspace_id,
            job_id=scope.job_id,
            feature=scope.feature,
            provider=self._provider.value,
            model=model,
            latency_ms=int((time.monotonic() - started) * 1000),
            **fields,  # type: ignore[arg-type]
        )

    async def chat(
        self,
        *,
        api_key: str,
        model: str,
        messages: list[ChatMessage],
        json_mode: bool = False,
        on_delta: DeltaHook | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        scope = current_scope()
        started = time.monotonic()
        try:
            result = await self._inner.chat(
                api_key=api_key, model=model, messages=messages, json_mode=json_mode, on_delta=on_delta,
                temperature=temperature,
            )
        except LlmProviderError as e:
            self._note(self._call(scope, model, started, ok=False, error_kind=e.kind.value))
            raise
        except Exception:
            self._note(self._call(scope, model, started, ok=False, error_kind="error"))
            raise
        self._note(
            self._call(
                scope,
                result.model or model,
                started,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                cached_prompt_tokens=result.cached_prompt_tokens,
                reasoning_tokens=result.reasoning_tokens,
            )
        )
        return result

    async def structured(self, *, api_key: str, model: str, messages: list[ChatMessage], schema: type[T]) -> T:
        # through chat(), so the first reply and the one repair are both recorded
        result = await self.chat(api_key=api_key, model=model, messages=messages, json_mode=True)
        try:
            return parse_structured(result.content, schema)
        except (ValueError, ValidationError) as e:
            repair = build_repair_messages([m.model_dump() for m in messages], result.content, e, schema)
            retry = await self.chat(api_key=api_key, model=model, messages=[ChatMessage(**m) for m in repair], json_mode=True)
            return parse_structured(retry.content, schema)

    async def probe_capabilities(self, *, api_key: str) -> LlmCapabilities:
        return await self._inner.probe_capabilities(api_key=api_key)
