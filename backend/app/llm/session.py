"""Resolve the caller's BYOK LLM into a ready-to-use session (client +
decrypted key + model). Shared by any phase that makes an LLM call on
behalf of a user; this returns `None` when no working key exists so callers
can degrade gracefully (Phase 5 discovery falls back to a deterministic
SearchPlan) or say plainly that a key is needed.

The client is metered (app/llm/usage.py): every call it makes is recorded
with the provider's own token usage. The model is the provider's default
unless `RESEARCHNEXUS_LLM_MODELS` names another, e.g.
`{"deepseek": "deepseek-v4-pro"}`.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.deps import get_llm_client
from app.domain.user import LlmProvider, User
from app.llm.capability_probe import default_model_for
from app.llm.client import LLMClient
from app.llm.usage import MeteredClient, db_recorder
from app.security.key_vault import KeyVault, KeyVaultDecryptionError
from app.telemetry.logging import get_logger

_log = get_logger(__name__)


@dataclass(frozen=True)
class LlmSession:
    client: LLMClient
    api_key: str
    model: str
    provider: LlmProvider


def model_for(provider: LlmProvider, settings: Settings) -> str:
    return settings.llm_models.get(provider.value) or default_model_for(provider)


def metered(client: LLMClient, db: Session, user: User, provider: LlmProvider) -> MeteredClient:
    return MeteredClient(client, owner_id=user.id, provider=provider, recorder=db_recorder(db.get_bind()))  # type: ignore[arg-type]


def resolve_llm_session(db: Session, user: User, settings: Settings) -> LlmSession | None:
    working = repo.pick_working_key(db, user.id, user.default_provider)
    if working is None:
        return None
    ciphertext = repo.get_api_key_ciphertext(db, user.id, working.provider)
    assert ciphertext is not None
    try:
        api_key = KeyVault(settings.key_vault_secret).decrypt(ciphertext)
    except KeyVaultDecryptionError:
        # saved under a different key-vault secret: unusable until saved again
        _log.warning("llm_key_undecryptable", provider=working.provider.value)
        return None
    return LlmSession(
        client=metered(get_llm_client(working.provider), db, user, working.provider),
        api_key=api_key,
        model=model_for(working.provider, settings),
        provider=working.provider,
    )
