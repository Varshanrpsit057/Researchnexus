from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timezone

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.db.models import ResearchProfileORM
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.paper import ParseConfidence, ParsedDocument, Section
from app.domain.profile import Confidence
from app.domain.user import ApiKeyStatus, LlmProvider
from app.llm.client import LlmProviderError
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.security.key_vault import KeyVault
from app.security.pdf_sanitizer import PdfFileMeta
from app.services.profile import pipeline as pipeline_module
from app.services.profile.pipeline import NoWorkingLlmKey, run_profile_extraction

_VALID_EXTRACTION_JSON = json.dumps(
    {
        "domain": {"value": "NLP", "quote": "We study a novel NLP problem."},
        "subdomains": {"items": []},
        "research_problem": {"value": "the problem", "quote": "We study a novel NLP problem."},
        "research_questions": {"items": []},
        "objectives": {"items": []},
        "keywords": ["nlp"],
        "methods": {"items": []},
        "models": {"items": []},
        "algorithms": {"items": []},
        "datasets": {"items": []},
        "evaluation_metrics": {"items": []},
        "findings": {"items": []},
        "limitations": {"items": []},
        "future_work": {"items": []},
        "important_entities": {"items": []},
        "cited_methods": {"items": []},
        "candidate_search_queries": ["nlp problem"],
    }
)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def settings() -> Settings:
    return Settings(_env_file=None, key_vault_secret=Fernet.generate_key().decode())  # type: ignore[call-arg]


def _seed_paper_with_chunks(db: Session) -> str:
    meta = PdfFileMeta(sha256="a" * 64, size_bytes=10, page_count=1, has_text_layer=True, encrypted=False)
    parsed = ParsedDocument(
        full_text="Abstract\nWe study a novel NLP problem.\nLimitations\nSome limitation text.\n",
        sections=[
            Section(title="Abstract", order=0, char_start=0, char_end=38, page_start=1, page_end=1),
            Section(title="Limitations", order=1, char_start=38, char_end=73, page_start=1, page_end=1),
        ],
        page_count=1,
        has_text_layer=True,
        parse_confidence=ParseConfidence.HIGH,
        title="A Seed Paper",
        authors=["A. Author"],
    )
    paper = repo.paper_from_ingest(paper_id="pap_1", meta=meta, parsed=parsed, pdf_path="x.pdf")
    repo.save_paper(db, paper)
    chunks = [
        PaperChunk(
            chunk_id="chk_1",
            paper_id="pap_1",
            section="Abstract",
            section_order=0,
            page=1,
            char_start=0,
            char_end=29,
            kind=ChunkKind.ABSTRACT,
            text="We study a novel NLP problem.",
            token_count=6,
        )
    ]
    repo.save_chunks(db, chunks)
    return "pap_1"


def _seed_working_key(db: Session, settings: Settings, provider: LlmProvider = LlmProvider.GROQ) -> None:
    user = repo.create_user(db, user_id="usr_1", email="researcher@example.com")
    vault = KeyVault(settings.key_vault_secret)
    repo.upsert_api_key(
        db,
        new_key_id="key_1",
        owner_id=user.id,
        provider=provider,
        key_ciphertext=vault.encrypt("sk-real-key"),
        key_last4="-key",
        status=ApiKeyStatus.WORKING,
        checked_at=datetime.now(timezone.utc),
    )


def _mock_client(handler: httpx.MockTransport) -> OpenAiCompatClient:
    return OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=handler))


def test_no_working_key_raises_no_working_llm_key(db: Session, settings: Settings) -> None:
    paper_id = _seed_paper_with_chunks(db)
    repo.create_user(db, user_id="usr_1", email="r@example.com")
    user = repo.get_user(db, "usr_1")
    paper = repo.get_paper(db, paper_id)
    assert user is not None
    assert paper is not None

    import asyncio

    with pytest.raises(NoWorkingLlmKey):
        asyncio.run(run_profile_extraction(db, paper, user, settings))


def test_successful_extraction_persists_profile(db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    paper_id = _seed_paper_with_chunks(db)
    _seed_working_key(db, settings)
    user = repo.get_user(db, "usr_1")
    paper = repo.get_paper(db, paper_id)
    assert user is not None
    assert paper is not None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": _VALID_EXTRACTION_JSON}}]})

    monkeypatch.setattr(pipeline_module, "get_llm_client", lambda provider: _mock_client(httpx.MockTransport(handler)))

    import asyncio

    result = asyncio.run(run_profile_extraction(db, paper, user, settings))

    assert result.profile.domain.value == "NLP"
    assert result.warnings == []
    stored = repo.get_profile(db, paper_id)
    assert stored is not None
    assert stored.domain.value == "NLP"


def test_extraction_failure_after_repair_persists_fallback_profile(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_id = _seed_paper_with_chunks(db)
    _seed_working_key(db, settings)
    user = repo.get_user(db, "usr_1")
    paper = repo.get_paper(db, paper_id)
    assert user is not None
    assert paper is not None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json at all"}}]})

    monkeypatch.setattr(pipeline_module, "get_llm_client", lambda provider: _mock_client(httpx.MockTransport(handler)))

    import asyncio

    result = asyncio.run(run_profile_extraction(db, paper, user, settings))

    assert result.warnings == ["profile_extraction_failed"]
    assert result.profile.extraction_confidence == Confidence.LOW
    assert result.profile.domain.value == ""
    stored = repo.get_profile(db, paper_id)
    assert stored is not None
    assert stored.extraction_confidence == Confidence.LOW


def test_provider_error_propagates_uncaught(db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    paper_id = _seed_paper_with_chunks(db)
    _seed_working_key(db, settings)
    user = repo.get_user(db, "usr_1")
    paper = repo.get_paper(db, paper_id)
    assert user is not None
    assert paper is not None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    monkeypatch.setattr(pipeline_module, "get_llm_client", lambda provider: _mock_client(httpx.MockTransport(handler)))

    import asyncio

    with pytest.raises(LlmProviderError):
        asyncio.run(run_profile_extraction(db, paper, user, settings))


def test_rerunning_analyze_updates_the_same_profile_row(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    paper_id = _seed_paper_with_chunks(db)
    _seed_working_key(db, settings)
    user = repo.get_user(db, "usr_1")
    paper = repo.get_paper(db, paper_id)
    assert user is not None
    assert paper is not None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": _VALID_EXTRACTION_JSON}}]})

    monkeypatch.setattr(pipeline_module, "get_llm_client", lambda provider: _mock_client(httpx.MockTransport(handler)))

    import asyncio

    first = asyncio.run(run_profile_extraction(db, paper, user, settings))
    second = asyncio.run(run_profile_extraction(db, paper, user, settings))

    # same logical resource (UNIQUE(paper_id, workspace_id)) -> stable id
    # across re-analysis, not a fresh identity on every call.
    assert first.profile.profile_id == second.profile.profile_id
    rows = db.execute(select(ResearchProfileORM).where(ResearchProfileORM.paper_id == paper_id)).scalars().all()
    assert len(rows) == 1
    assert rows[0].id == second.profile.profile_id
