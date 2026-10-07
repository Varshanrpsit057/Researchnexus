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
        if "semanticscholar.org" in url:  # seed resolution / S2 lookups: not on S2
            return httpx.Response(404, json={})
        if "europepmc" in url:
            return httpx.Response(200, json={"resultList": {"result": []}})
        if "crossref.org" in url:
            return httpx.Response(200, json={"message": {"items": []}})
        if "dblp.org" in url:
            return httpx.Response(200, json={"result": {"hits": {}}})
        if "core.ac.uk" in url:
            return httpx.Response(200, json={"results": []})
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


def test_an_unreadable_saved_key_falls_back_instead_of_failing_discovery(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A key saved under a since-changed vault secret can't be decrypted.
    # Discovery never requires a key, so that must not fail the run.
    from app.domain.user import User
    from app.security.key_vault import KeyVaultDecryptionError
    from app.services.discovery import pipeline as discovery_pipeline

    def unreadable(*_a: object, **_k: object) -> None:
        raise KeyVaultDecryptionError("stored key could not be decrypted")

    monkeypatch.setattr(discovery_pipeline, "resolve_llm_session", unreadable)
    seed_id = _seed(db)
    user = User(id="usr_1", email="u@example.com", auth_subject="u@example.com")
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=user, settings=settings, options=_options()))
    assert "search_plan_fallback_key_unusable" in result.warnings
    assert repo.get_search_run(db, result.run_id) is not None


# --- remediation Phase 8: a run says what it is doing, and keeps how it went -------


def test_a_run_reports_each_step_as_it_goes_and_is_saved_with_that_report(db: Session, settings: Settings) -> None:
    from app.services.discovery.progress import DiscoveryProgress

    seed_id = _seed(db)
    written: list[dict] = []
    progress = DiscoveryProgress(written.append, min_interval_s=0.0)
    opts = _options()
    opts.progress = progress
    # as the pipeline's own client is built: every request reported to the run
    opts.http = ExternalHttpClient(transport=_handler(), sleep=_no_sleep, on_request=progress.on_request)
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=None, settings=settings, options=opts))

    # live: the search step was seen running, and papers were counted as they arrived
    assert any(w["step"] == "search" for w in written)
    assert any(w["found"] > 0 for w in written)
    last = written[-1]
    assert [last["steps"][s]["state"] for s in ("plan", "resolve", "search", "score", "save")] == ["done"] * 5
    assert last["steps"]["plan"]["note"] == "fallback"  # no key: the deterministic plan
    assert last["sources"]["openalex"]["answered"] >= 1

    run = repo.get_search_run(db, result.run_id)
    assert run is not None and run.report is not None
    assert run.report["status"] == result.status
    assert run.report["strategies"]["keyword"]["state"] == "done"
    # the saved report ends with the save, done; ranking and relationships come after it
    assert run.report["steps"]["save"]["state"] == "done"
    assert "rank" not in run.report["steps"] and "trail" not in run.report["steps"]
    assert run.report["strategies"]["keyword"]["found"] >= 1
    assert "search_plan_fallback_no_llm" in run.report["warnings"]
    # the run records when it really started, not when it was saved
    assert run.finished_at is not None and run.started_at < run.finished_at


def test_candidates_read_back_in_the_order_discovery_produced_them(db: Session, settings: Settings) -> None:
    seed_id = _seed(db)
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=None, settings=settings, options=_options()))
    ids = [c.candidate_id for c in repo.get_search_candidates(db, result.run_id)]
    assert ids == [f"cand_{result.run_id.removeprefix('run_')}_{i:04d}" for i in range(1, len(ids) + 1)]


def test_a_search_plan_that_runs_over_its_limit_gives_way_to_the_deterministic_one(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.user import User
    from app.services.discovery import pipeline as discovery_pipeline

    async def slow_plan(*_a: object, **_k: object) -> object:
        await asyncio.sleep(5)
        raise AssertionError("should have been stopped")

    monkeypatch.setattr(discovery_pipeline, "resolve_llm_session", lambda *_a, **_k: object())
    monkeypatch.setattr(discovery_pipeline, "generate_search_plan", slow_plan)
    monkeypatch.setattr(discovery_pipeline, "_PLAN_TIMEOUT_S", 0.05)
    seed_id = _seed(db)
    user = User(id="usr_1", email="u@example.com", auth_subject="u@example.com")
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=user, settings=settings, options=_options()))
    assert "search_plan_fallback_timeout" in result.warnings
    assert repo.get_search_candidates(db, result.run_id)  # the run went on with the fallback plan


def test_two_candidates_that_land_on_one_stored_paper_are_listed_once(db: Session, settings: Settings) -> None:
    # dedupe keeps them apart (no shared id), but the stored paper matches
    # one by DOI and the other by title: the run lists it once instead of
    # breaking its (run, paper) uniqueness and failing
    from app.db.models import PaperORM

    seed_id = _seed(db)
    db.add(PaperORM(id="pap_known", title="Known Title", title_hash=title_hash("Known Title"), doi="10.1/known", source="discovery"))
    db.commit()

    def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openalex.org" in url and "/works/" not in url and "search=" in url:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "https://openalex.org/W7", "doi": "https://doi.org/10.1/known", "title": "A Different Title", "publication_year": 2021},
                        {"id": "https://openalex.org/W8", "doi": None, "title": "Known Title", "publication_year": 2021},
                    ]
                },
            )
        if "arxiv.org" in url:
            return httpx.Response(200, text='<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        if "europepmc" in url:
            return httpx.Response(200, json={"resultList": {"result": []}})
        return httpx.Response(404, json={})

    opts = DiscoveryOptions(
        http=ExternalHttpClient(transport=httpx.MockTransport(h), sleep=_no_sleep),
        strategies=[DiscoveryStrategy.KEYWORD],
        per_strategy_timeout_s=5.0,
    )
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=None, settings=settings, options=opts))
    paper_ids = list(repo.get_search_candidate_paper_ids(db, result.run_id).values())
    assert paper_ids.count("pap_known") == 1


def test_the_search_plan_and_the_seed_lookup_run_side_by_side(
    db: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # the seed lookup needs no plan: waiting for the model before asking
    # OpenAlex and Semantic Scholar cost 3-4 s a run
    from app.services.discovery import pipeline as discovery_pipeline
    from app.services.search_concepts.concept_generator import fallback_plan

    async def slow_plan(profile, *, session, citation_anchors):  # noqa: ANN001, ARG001
        await asyncio.sleep(0.4)
        return fallback_plan(profile, citation_anchors=citation_anchors), []

    monkeypatch.setattr(discovery_pipeline, "generate_search_plan", slow_plan)
    seed_id = _seed(db)
    result = asyncio.run(run_discovery(db, seed_paper_id=seed_id, current_user=None, settings=settings, options=_options()))
    run = repo.get_search_run(db, result.run_id)
    assert run is not None and run.report is not None
    plan, resolve = run.report["steps"]["plan"], run.report["steps"]["resolve"]
    assert resolve["started_s"] < plan["started_s"] + plan["seconds"]  # it began before the plan was ready


def test_a_seed_lookup_that_was_refused_is_never_reported_as_not_found() -> None:
    # found on a real run: OpenAlex refused the lookup (its keyless budget was
    # spent) and the page said the seed was "not found on OpenAlex"
    from app.services.discovery.base import SeedView, StrategyContext
    from app.services.discovery.budget import DiscoveryBudget
    from app.services.discovery.pipeline import _resolve_outcome

    def ctx(openalex: bool = False, s2: bool = False) -> StrategyContext:
        seed = SeedView(paper_id="p", title="T", openalex_work={"id": "W1"} if openalex else None, s2_paper_id="S" if s2 else None)
        return StrategyContext(seed=seed, seed_chunks=[], plan=None, filters=None, budget=DiscoveryBudget(), http=None)  # type: ignore[arg-type]

    assert _resolve_outcome(ctx(), ["resolve_openalex_failed"]) == {"state": "failed", "note": "OpenAlex couldn't be asked; not on Semantic Scholar"}
    assert _resolve_outcome(ctx(s2=True), ["resolve_openalex_failed"]) == {
        "state": "done", "note": "found on Semantic Scholar; OpenAlex couldn't be asked",
    }
    assert _resolve_outcome(ctx(), []) == {"state": "done", "note": "not found on OpenAlex or Semantic Scholar"}
    assert _resolve_outcome(ctx(), ["resolve_timed_out"]) == {"state": "failed", "note": "the lookup ran out of time"}
    assert _resolve_outcome(ctx(openalex=True, s2=True), []) == {"state": "done", "note": "found on OpenAlex and Semantic Scholar"}
