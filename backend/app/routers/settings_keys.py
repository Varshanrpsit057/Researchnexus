"""`GET|PUT|DELETE /api/v1/settings/llm-keys`, `POST .../test` -- Roadmap
Task 1 item 6; API spec §3. The raw key is only ever held in memory for the
duration of one request (Architecture §7: never hold a BYOK key longer than
a request).
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import repository as repo
from app.deps import AppSettings, CurrentUser, DbSession
from app.domain.user import ApiKeyRecord, ApiKeyStatus, LlmProvider
from app.jobs.runner import new_id
from app.llm.capability_probe import probe
from app.security.key_vault import KeyVault

router = APIRouter(tags=["settings"])


class ApiKeyRequest(BaseModel):
    provider: str
    api_key: str


def _parse_provider(raw: str) -> LlmProvider:
    try:
        return LlmProvider(raw)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail={"error": {"code": "unsupported_provider", "message": f"unknown provider '{raw}'"}},
        ) from e


def _serialize(record: ApiKeyRecord) -> dict[str, object]:
    return {
        "provider": record.provider.value,
        "status": record.status.value,
        "key_last4": record.key_last4,
        "checked_at": record.checked_at.isoformat() if record.checked_at else None,
    }


@router.get("/api/v1/settings/llm-keys")
def list_keys(current_user: CurrentUser, db: DbSession) -> dict[str, object]:
    records = repo.list_api_keys(db, current_user.id)
    return {"keys": [_serialize(r) for r in records]}


@router.post("/api/v1/settings/llm-keys/test")
async def test_key(body: ApiKeyRequest, current_user: CurrentUser) -> dict[str, object]:
    provider = _parse_provider(body.provider)
    result = await probe(provider, body.api_key)
    return result.model_dump(mode="json", exclude_none=True)


@router.put("/api/v1/settings/llm-keys")
async def put_key(body: ApiKeyRequest, current_user: CurrentUser, db: DbSession, settings: AppSettings) -> dict[str, object]:
    provider = _parse_provider(body.provider)
    result = await probe(provider, body.api_key)
    vault = KeyVault(settings.key_vault_secret)
    record = repo.upsert_api_key(
        db,
        new_key_id=new_id("key"),
        owner_id=current_user.id,
        provider=provider,
        key_ciphertext=vault.encrypt(body.api_key),
        key_last4=body.api_key[-4:],
        status=ApiKeyStatus.WORKING if result.success else ApiKeyStatus.FAILED,
        checked_at=datetime.now(timezone.utc),
    )
    return _serialize(record)


@router.post("/api/v1/settings/llm-keys/{provider}/check")
async def check_key(provider: str, current_user: CurrentUser, db: DbSession, settings: AppSettings) -> dict[str, object]:
    """Probe the stored key again -- a key can be revoked or run out of credit
    after it was saved. Decrypted for this request only; never returned."""
    parsed = _parse_provider(provider)
    ciphertext = repo.get_api_key_ciphertext(db, current_user.id, parsed)
    stored = next((k for k in repo.list_api_keys(db, current_user.id) if k.provider == parsed), None)
    if ciphertext is None or stored is None:
        raise HTTPException(
            status_code=404, detail={"error": {"code": "not_found", "message": f"no {parsed.value} key saved"}}
        )
    result = await probe(parsed, KeyVault(settings.key_vault_secret).decrypt(ciphertext))
    record = repo.upsert_api_key(
        db,
        new_key_id=stored.id,
        owner_id=current_user.id,
        provider=parsed,
        key_ciphertext=ciphertext,
        key_last4=stored.key_last4,
        status=ApiKeyStatus.WORKING if result.success else ApiKeyStatus.FAILED,
        checked_at=datetime.now(timezone.utc),
    )
    return {"key": _serialize(record), "result": result.model_dump(mode="json", exclude_none=True)}


@router.delete("/api/v1/settings/llm-keys/{provider}", status_code=204)
def delete_key(provider: str, current_user: CurrentUser, db: DbSession) -> None:
    parsed = _parse_provider(provider)
    repo.delete_api_key(db, current_user.id, parsed)
