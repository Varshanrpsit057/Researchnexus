"""Chat session/message domain models (Data Model §13 `chat_sessions` /
`chat_messages`; Roadmap Phase 9).

An assistant message's `citations` is the list of `Claim.claim_id`s that
ground it -- the message text itself never carries reference strings.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ChatRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatSession(BaseModel):
    session_id: str
    workspace_id: str
    owner_id: str
    title: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


class ChatMessage(BaseModel):
    message_id: str
    session_id: str
    role: ChatRole
    content: str = ""
    citations: list[str] = Field(default_factory=list)  # Claim.claim_id list
    tokens_prompt: int = 0
    tokens_completion: int = 0
    faithfulness: float | None = None
    answerable: bool = True
    # assistant turns: why the answer looks the way it does
    suggestion: str | None = None  # what to try instead, when not answerable
    unsupported_dropped: int = 0  # sentences cut for lacking a supporting source
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
