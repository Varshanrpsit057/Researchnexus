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
from app.domain.user import User
from app.jobs.runner import new_id
from app.llm.client import LlmProviderError
from app.llm.session import LlmSession, metered, model_for
from app.llm.usage import usage_scope_default
from app.security.key_vault import KeyVault
from app.services.ingest.abstract_chunks import ensure_abstract_chunks
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

    working_key = repo.pick_working_key(db, current_user.id, current_user.default_provider)
    if working_key is None:
        raise NoWorkingLlmKey()

    ciphertext = repo.get_api_key_ciphertext(db, current_user.id, working_key.provider)
    assert ciphertext is not None  # invariant: a listed key row always has ciphertext
    api_key = KeyVault(settings.key_vault_secret).decrypt(ciphertext)

    llm_client = metered(get_llm_client(working_key.provider), db, current_user, working_key.provider)
    model = model_for(working_key.provider, settings)
    authors = list(paper.authors or [])

    try:
        with usage_scope_default("profile"):
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


async def profile_with_session(
    db: Session, paper: PaperORM, session: LlmSession, settings: Settings
) -> ResearchProfile | None:
    """The lazy, first-use profile a workspace paper gets when a later stage
    needs one (the gap engine): from its full text when it has one, else from
    its abstract, flagged `grounding="abstract"` so evidence from it is
    down-weighted (Seed_Paper_Research_Trail: "related-paper profiles are
    grounded in abstracts"). Nothing is stored when the paper has no text or
    the extraction fails -- an empty fallback profile would stand in for a
    real one and block a later attempt."""
    grounding = "full_text" if paper.has_full_text else "abstract"
    ensure_abstract_chunks(db, [paper.id])
    chunks = repo.get_chunks_for_paper(db, paper.id)
    if not chunks:
        return None
    try:
        extraction, tokens = await extract_profile(
            session.client,
            api_key=session.api_key,
            model=session.model,
            chunks=chunks,
            max_context_chars=settings.profile_max_context_chars,
        )
    except (ProfileExtractionFailed, LlmProviderError):
        return None
    profile, _warnings = build_profile(
        profile_id=new_id("prof"),
        paper_id=paper.id,
        title=paper.title,
        authors=list(paper.authors or []),
        year=paper.year,
        venue=paper.venue,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        chunks=chunks,
        sections=[Section(**s) for s in paper.sections or []],
        extraction=extraction,
        extraction_model=f"{session.provider.value}:{session.model}",
        tokens=tokens,
        grounding=grounding,
    )
    return repo.upsert_profile(db, profile)
