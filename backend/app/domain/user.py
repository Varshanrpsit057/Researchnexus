"""User + BYOK API-key domain models (Roadmap Phase 1; Data Model §13).

`ApiKeyRecord` is the redacted, storage-agnostic view returned to clients --
it never carries `key_ciphertext` (Architecture §7: "plaintext never stored/
logged"; API spec §3: GET .../llm-keys "never returns ciphertext or full
key").
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LlmProvider(str, Enum):
    """Fixed provider allowlist (Architecture §7) -- an SSRF control: the
    backend only ever calls one of these hosts, never a user-supplied URL."""

    OPENAI = "openai"
    GROQ = "groq"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"
    TOGETHER = "together"
    GEMINI = "gemini"


class ApiKeyStatus(str, Enum):
    UNVERIFIED = "unverified"
    WORKING = "working"
    FAILED = "failed"


class User(BaseModel):
    id: str
    email: str
    auth_provider: str = "local"
    auth_subject: str
    created_at: datetime = Field(default_factory=_utcnow)
    default_provider: LlmProvider | None = None


class ApiKeyRecord(BaseModel):
    """Redacted view of a stored key -- see module docstring."""

    id: str
    owner_id: str
    provider: LlmProvider
    key_last4: str
    status: ApiKeyStatus
    checked_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class LlmCapabilities(BaseModel):
    json_mode: bool
    context_tokens: int
    streaming: bool


class LlmTestResult(BaseModel):
    success: bool
    latency_ms: int | None = None
    capabilities: LlmCapabilities | None = None
    message: str | None = None
