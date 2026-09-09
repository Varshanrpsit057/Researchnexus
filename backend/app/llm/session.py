"""Resolve the caller's BYOK LLM into a ready-to-use session (client +
decrypted key + default model). Shared by any phase that makes an LLM call
on behalf of a user; unlike Phase 3's `run_profile_extraction` (which
*requires* a key), this returns `None` when no working key exists so
callers can degrade gracefully (Phase 5 discovery falls back to a
deterministic SearchPlan).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.deps import get_llm_client
from app.domain.user import ApiKeyStatus, LlmProvider, User
from app.llm.capability_probe import default_model_for
from app.llm.client import LLMClient
from app.security.key_vault import KeyVault


@dataclass(frozen=True)
class LlmSession:
    client: LLMClient
    api_key: str
    model: str
    provider: LlmProvider


def resolve_llm_session(db: Session, user: User, settings: Settings) -> LlmSession | None:
    working = next((k for k in repo.list_api_keys(db, user.id) if k.status == ApiKeyStatus.WORKING), None)
    if working is None:
        return None
    ciphertext = repo.get_api_key_ciphertext(db, user.id, working.provider)
    assert ciphertext is not None
    return LlmSession(
        client=get_llm_client(working.provider),
        api_key=KeyVault(settings.key_vault_secret).decrypt(ciphertext),
        model=default_model_for(working.provider),
        provider=working.provider,
    )
