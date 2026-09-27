"""Model-provider usage (remediation Phase 2): one `LlmCall` per call to a
provider, with the provider's own token counts. See `LlmCallORM`."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LlmCall(BaseModel):
    id: str
    owner_id: str
    workspace_id: str | None = None
    job_id: str | None = None
    # what the call was for: chat, profile, gaps, directions, compare, ...
    feature: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: int = 0
    ok: bool = True
    error_kind: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
