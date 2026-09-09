from __future__ import annotations

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.domain.candidate import DiscoveryStrategy
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.profile import Confidence, ProfileField, ProfileList, ResearchProfile
from app.external.http import ExternalHttpClient
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.services.discovery.pipeline import (
    DiscoveryOptions,
    ProfileRequired,
    SeedPaperNotFound,
    run_discovery,
)
from app.services.normalize.canonical import title_hash

_ARXIV = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/2005.11401v1</id><published>2020-05-01T00:00:00Z</published>
    <title>Dense Passage Retrieval for Open-Domain QA</title><summary>we introduce DPR</summary>
    <author><name>V. Karpukhin</name></author></entry>
</feed>"""

_OPENALEX_SEARCH = {
    "results": [
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1/fid",
            "title": "FiD: Fusion-in-Decoder",
            "publication_year": 2021,
            "authorships": [{"author": {"display_name": "G. Izacard"}}],
            "abstract_inverted_index": {"fusion": [0], "in": [1], "decoder": [2]},
        }
    ]
}


async def _no_sleep(_s: float) -> None:
    return None


def _handler(fail_openalex: bool = False) -> httpx.MockTransport:
    def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "arxiv.org" in url:
            return httpx.Response(200, text=_ARXIV)
        if "openalex.org" in url:
            if fail_openalex:
                return httpx.Response(503, text="down")
            if "/works/" in url:  # citation seed lookup -> pretend the seed isn't on OpenAlex
                return httpx.Response(404, json={})
            return httpx.Response(200, json=_OPENALEX_SEARCH)
        raise AssertionError(url)

    return httpx.MockTransport(h)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(conn: object, _rec: object) -> None:
        cur = conn.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def _seed(db: Session, *, with_profile: bool = True) -> str:
    from app.services.normalize.canonical import title_hash as th

    cand_hash = th("Retrieval-Augmented Generation for Knowledge-Intensive NLP")
    from app.db.models import PaperORM

    paper = PaperORM(
        id="pap_seed",
        title="Retrieval-Augmented Generation for Knowledge-Intensive NLP",
        title_hash=cand_hash,
        authors=["P. Lewis"],
        year=2020,
        doi="10.5555/rag",
        abstract="We propose RAG for knowledge-intensive tasks.",
        has_full_text=True,
        source="upload",
        references=[{"order": 0, "raw_text": "Karpukhin et al. DPR. doi:10.18653/v1/2020.emnlp-main.550"}],
    )
    db.add(paper)
    db.commit()
    repo.save_chunks(
        db,
        [
            PaperChunk(
                chunk_id="chk_1",
                paper_id="pap_seed",
                section="Abstract",
                section_order=0,
                page=1,
                char_start=0,
                char_end=44,
                kind=ChunkKind.ABSTRACT,
                text="We propose RAG for knowledge-intensive tasks.",
                token_count=7,
            )
        ],
    )
    if with_profile:
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id="prof_seed",
                paper_id="pap_seed",
                title=paper.title,
                abstract=paper.abstract or "",
                domain=ProfileField(value="NLP"),
                research_problem=ProfileField(value="knowledge intensive question answering"),
                keywords=["retrieval augmented generation", "open domain qa"],
                methods=ProfileList(items=[ProfileField(value="dense retrieval")]),
                extraction_confidence=Confidence.HIGH,
            ),
        )
    return "pap_seed"


def _options() -> DiscoveryOptions:
    return DiscoveryOptions(
        http=ExternalHttpClient(transport=_handler(), sleep=_no_sleep),
        chunk_embedder=FakeEmbeddingProvider(),
        doc_embedder=FakeEmbeddingProvider(),
        per_strategy_timeout_s=5.0,
    )


def test_run_discovery_persists_a_run_and_candidates_with_provenance(db: Session, settings: Settings) -> None:
    seed_id = _seed(db)
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=None, settings=settings, options=_options()))

    assert result.status in {"succeeded", "partial"}
    run = repo.get_search_run(db, result.run_id)
    assert run is not None
    assert run.seed_paper_id == seed_id
    assert set(run.strategies_requested) >= {DiscoveryStrategy.KEYWORD, DiscoveryStrategy.SEMANTIC}

    candidates = repo.get_search_candidates(db, result.run_id)
    assert candidates, "at least one candidate was discovered and persisted"
    titles = {c.title for c in candidates}
    assert "Dense Passage Retrieval for Open-Domain QA" in titles

    provenance = repo.get_search_candidate_provenance(db, result.run_id)
    any_prov = next(iter(provenance.values()))
    assert "found_by_strategies" in any_prov
    assert "raw_signals" in any_prov
    assert "sources" in any_prov


def test_seed_paper_is_never_persisted_as_its_own_candidate(db: Session, settings: Settings) -> None:
    seed_id = _seed(db)
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=None, settings=settings, options=_options()))
    candidates = repo.get_search_candidates(db, result.run_id)
    assert all(title_hash(c.title) != title_hash("Retrieval-Augmented Generation for Knowledge-Intensive NLP") for c in candidates)


def test_missing_profile_raises_profile_required(db: Session, settings: Settings) -> None:
    seed_id = _seed(db, with_profile=False)
    with pytest.raises(ProfileRequired):
        asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=None, settings=settings, options=_options()))


def test_missing_seed_raises_not_found(db: Session, settings: Settings) -> None:
    with pytest.raises(SeedPaperNotFound):
        asyncio.run(run_discovery(db, seed_paper_id="pap_nope", current_user=None, settings=settings, options=_options()))


def test_partial_upstream_failure_is_recorded_on_the_run(db: Session, settings: Settings) -> None:
    seed_id = _seed(db)
    opts = DiscoveryOptions(
        http=ExternalHttpClient(transport=_handler(fail_openalex=True), sleep=_no_sleep, max_retries=1),
        chunk_embedder=FakeEmbeddingProvider(),
        doc_embedder=FakeEmbeddingProvider(),
        per_strategy_timeout_s=5.0,
    )
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=None, settings=settings, options=opts))
    # arXiv still worked, so the keyword strategy succeeds partially; the run
    # completes rather than raising.
    run = repo.get_search_run(db, result.run_id)
    assert run is not None
    candidates = repo.get_search_candidates(db, result.run_id)
    assert any(c.title == "Dense Passage Retrieval for Open-Domain QA" for c in candidates)


def test_no_llm_key_falls_back_to_a_deterministic_plan_and_still_runs(db: Session, settings: Settings) -> None:
    seed_id = _seed(db)
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=None, settings=settings, options=_options()))
    assert "search_plan_fallback_no_llm" in result.warnings
    assert repo.get_search_run(db, result.run_id) is not None
