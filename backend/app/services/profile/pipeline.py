"""Stage S4 orchestration: fetch the paper's chunks, decrypt the caller's
BYOK key, run extraction, resolve provenance, persist. Mirrors the shape of
app/services/ingest/pipeline.py -- the router stays thin and this is the
one place that knows the end-to-end flow (Architecture §2: routers "must
NOT do retrieval/LLM work inline").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.db.models import PaperORM
from app.deps import get_llm_client
from app.domain.paper import Section
from app.domain.profile import ResearchProfile
from app.domain.user import ApiKeyStatus, User
from app.jobs.runner import new_id
from app.llm.capability_probe import default_model_for
from app.security.key_vault import KeyVault
from app.services.profile.extractor import ProfileExtractionFailed, extract_profile
from app.services.profile.validator import build_fallback_profile, build_profile


class NoWorkingLlmKey(Exception):
    """No stored `api_keys` row has `status=working` for this user (API
    spec §1.1 `409 llm_key_required`)."""


@dataclass(frozen=True)
class AnalyzeResult:
    profile: ResearchProfile
    warnings: list[str] = field(default_factory=list)


async def run_profile_extraction(
    db: Session, paper: PaperORM, current_user: User, settings: Settings
) -> AnalyzeResult:
    chunks = repo.get_chunks_for_paper(db, paper.id)
    sections = [Section(**s) for s in paper.sections]

    api_keys = repo.list_api_keys(db, current_user.id)
    working_key = next((k for k in api_keys if k.status == ApiKeyStatus.WORKING), None)
    if working_key is None:
        raise NoWorkingLlmKey()

    ciphertext = repo.get_api_key_ciphertext(db, current_user.id, working_key.provider)
    assert ciphertext is not None  # invariant: a listed key row always has ciphertext
    api_key = KeyVault(settings.key_vault_secret).decrypt(ciphertext)

    llm_client = get_llm_client(working_key.provider)
    model = default_model_for(working_key.provider)
    authors = list(paper.authors or [])

    try:
        extraction, tokens = await extract_profile(
            llm_client,
            api_key=api_key,
            model=model,
            chunks=chunks,
            max_context_chars=settings.profile_max_context_chars,
        )
    except ProfileExtractionFailed:
        profile = build_fallback_profile(
            profile_id=new_id("prof"),
            paper_id=paper.id,
            title=paper.title,
            authors=authors,
            year=paper.year,
            venue=paper.venue,
            doi=paper.doi,
            arxiv_id=paper.arxiv_id,
            chunks=chunks,
        )
        stored = repo.upsert_profile(db, profile)
        return AnalyzeResult(profile=stored, warnings=["profile_extraction_failed"])

    profile, warnings = build_profile(
        profile_id=new_id("prof"),
        paper_id=paper.id,
        title=paper.title,
        authors=authors,
        year=paper.year,
        venue=paper.venue,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        chunks=chunks,
        sections=sections,
        extraction=extraction,
        extraction_model=f"{working_key.provider.value}:{model}",
        tokens=tokens,
    )
    stored = repo.upsert_profile(db, profile)
    return AnalyzeResult(profile=stored, warnings=warnings)
