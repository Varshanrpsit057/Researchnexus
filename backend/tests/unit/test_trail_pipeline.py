from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperORM
from app.domain.candidate import (
    CitationRelationship,
    DiscoveryStrategy,
    NormalizedCandidate,
    SearchRun,
)
from app.domain.profile import Confidence, ProfileField, ProfileList, ResearchProfile, SourceSpan
from app.domain.ranking import (
    RankedPaper,
    RankingExplanation,
    SignalScores,
)
from app.domain.trail import RelationshipType, UserState
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.normalize.canonical import title_hash
from app.services.trail.pipeline import (
    RankingRequired,
    RunNotFound,
    SeedNotReady,
    TrailOptions,
    build_trail,
)


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


def _seed(db: Session) -> str:
    db.add(
        PaperORM(
            id="pap_seed",
            title="Retrieval-Augmented Generation for Knowledge-Intensive NLP",
            title_hash=title_hash("Retrieval-Augmented Generation for Knowledge-Intensive NLP"),
            year=2020,
            abstract="We combine parametric and non-parametric memory for knowledge-intensive tasks.",
            has_full_text=True,
            source="upload",
        )
    )
    db.commit()
    repo.upsert_profile(
        db,
        ResearchProfile(
            profile_id="prof_seed",
            paper_id="pap_seed",
            title="RAG",
            abstract="We propose RAG.",
            domain=ProfileField(value="NLP"),
            research_problem=ProfileField(value="knowledge intensive question answering"),
            keywords=["retrieval augmented generation"],
            methods=ProfileList(items=[ProfileField(value="dense retrieval")]),
            datasets=ProfileList(
                items=[
                    ProfileField(
                        value="Natural Questions",
                        source_span=SourceSpan(paper_id="pap_seed", quote="Natural Questions"),
                    )
                ]
            ),
            findings=ProfileList(
                items=[
                    ProfileField(
                        value="Retrieval-augmented generation reduces hallucination.",
                        source_span=SourceSpan(
                            paper_id="pap_seed", quote="Retrieval-augmented generation reduces hallucination."
                        ),
                    )
                ]
            ),
            extraction_confidence=Confidence.HIGH,
        ),
    )
    return "pap_seed"


def _add_candidate(
    db: Session,
    run_id: str,
    *,
    cand_id: str,
    title: str,
    abstract: str,
    year: int | None,
    rel: CitationRelationship,
    hops: int | None,
    signals: SignalScores,
    rank: int,
) -> str:
    pid = repo.upsert_discovered_paper(
        db, NormalizedCandidate(title=title, title_hash=title_hash(title), abstract=abstract, year=year)
    )
    repo.add_search_candidate(
        db,
        candidate_id=cand_id,
        run_id=run_id,
        paper_id=pid,
        discovery_methods=[DiscoveryStrategy.KEYWORD],
        possible_duplicate_of=None,
        provenance={},
        citation_relationship=rel,
        citation_hops=hops,
    )
    repo.save_ranked_papers(
        db,
        run_id,
        repo.get_ranked_papers(db, run_id)
        + [
            RankedPaper(
                candidate_id=cand_id,
                signals=signals,
                weights_version="w0-initial",
                fused_score=1.0 / rank,
                rerank_score=None,
                final_rank=rank,
                band=Confidence.MEDIUM,
                explanation=RankingExplanation(bullet_reasons=["x"], prose="x."),
            )
        ],
        {**repo.get_search_candidate_paper_ids(db, run_id)},
    )
    return pid


def _build_run(db: Session) -> str:
    seed_id = _seed(db)
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed_id))
    _add_candidate(
        db, "run_1", cand_id="c_found", title="Dense Passage Retrieval", abstract="DPR for open-domain QA.",
        year=2016, rel=CitationRelationship.CITED_BY_SEED, hops=1, signals=SignalScores(semantic_doc=0.6), rank=1,
    )
    _add_candidate(
        db, "run_1", cand_id="c_ds", title="A Benchmark Paper", abstract="We evaluate on Natural Questions.",
        year=2021, rel=CitationRelationship.NONE, hops=None, signals=SignalScores(dataset_overlap=0.4), rank=2,
    )
    _add_candidate(
        db, "run_1", cand_id="c_none", title="Protein Folding Advances", abstract="Alphafold-style modelling.",
        year=2019, rel=CitationRelationship.NONE, hops=None, signals=SignalScores(semantic_doc=0.05), rank=3,
    )
    return "run_1"


def _session(handler: httpx.MockTransport) -> LlmSession:
    from app.domain.user import LlmProvider

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=handler)),
        api_key="sk-x",
        model="m",
        provider=LlmProvider.GROQ,
    )


def test_build_trail_without_a_session_creates_rule_only_edges(db: Session, settings: Settings) -> None:
    run_id = _build_run(db)
    result = asyncio.run(build_trail(db, run_id=run_id, settings=settings, options=TrailOptions()))

    assert result.edge_count >= 2
    assert result.unknown_targets == 1  # the protein-folding paper
    assert result.contradiction_edges == 0  # no session -> no contradiction edges

    edges = repo.get_trail_edges(db, run_id)
    kinds = {(e.target_paper_id, e.relationship_type) for e in edges}
    found_target = next(e.target_paper_id for e in edges if e.relationship_type == RelationshipType.FOUNDATIONAL)
    assert (found_target, RelationshipType.FOUNDATIONAL) in kinds
    assert any(e.relationship_type == RelationshipType.DATASET_RELATED for e in edges)
    assert all(e.detection_method.value == "rule" for e in edges)
    assert all(e.evidence for e in edges)  # never an edge without evidence
    assert all(e.confidence != Confidence.HIGH for e in edges)  # HIGH needs LLM confirmation


def test_build_trail_with_a_confirming_session_marks_edges_rule_llm_confirmed(db: Session, settings: Settings) -> None:
    run_id = _build_run(db)

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if "NLI" in body or "CONTRADICT" in body:
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({"contradiction": False})}}]})
        payload = {
            "confirmations": [
                {"relationship_type": "FOUNDATIONAL", "confirmed": True, "target_span": "DPR for open-domain QA.", "certainty": "high"},
                {"relationship_type": "DATASET_RELATED", "confirmed": True, "target_span": "We evaluate on Natural Questions.", "certainty": "medium"},
            ]
        }
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    result = asyncio.run(
        build_trail(db, run_id=run_id, settings=settings, options=TrailOptions(session=_session(httpx.MockTransport(handler))))
    )
    assert result.edge_count >= 2
    edges = repo.get_trail_edges(db, run_id)
    found = next(e for e in edges if e.relationship_type == RelationshipType.FOUNDATIONAL)
    assert found.detection_method.value == "rule_llm_confirmed"
    assert found.llm_confirmed is True
    assert found.confidence == Confidence.HIGH  # HIGH rule + LLM high certainty + signal agreement


def test_contradiction_edge_is_created_only_with_a_verified_span_from_both_papers(db: Session, settings: Settings) -> None:
    seed_id = _seed(db)
    repo.create_search_run(db, SearchRun(run_id="run_c", seed_paper_id=seed_id))
    _add_candidate(
        db, "run_c", cand_id="c_contra", title="A Contrarian Study",
        abstract="We find that retrieval does not reduce hallucination in long-form generation.",
        year=2023, rel=CitationRelationship.NONE, hops=None, signals=SignalScores(problem_sim=0.7), rank=1,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        if "NLI checker" in body:
            payload = {
                "contradiction": True,
                "seed_span": "Retrieval-augmented generation reduces hallucination.",
                "target_span": "retrieval does not reduce hallucination in long-form generation",
            }
        else:
            payload = {"confirmations": []}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    result = asyncio.run(
        build_trail(db, run_id="run_c", settings=settings, options=TrailOptions(session=_session(httpx.MockTransport(handler))))
    )
    assert result.contradiction_edges == 1
    edge = next(e for e in repo.get_trail_edges(db, "run_c") if e.relationship_type == RelationshipType.POTENTIALLY_CONTRADICTORY)
    assert edge.detection_method.value == "contradiction_nli"
    assert {ev.role for ev in edge.evidence} == {"seed_claim", "target_claim"}
    assert edge.confidence in {Confidence.MEDIUM, Confidence.LOW}  # never HIGH


def test_repeated_runs_are_deterministic(db: Session, settings: Settings) -> None:
    run_id = _build_run(db)
    asyncio.run(build_trail(db, run_id=run_id, settings=settings, options=TrailOptions()))
    first = [e.model_dump(exclude={"created_at"}) for e in repo.get_trail_edges(db, run_id)]
    asyncio.run(build_trail(db, run_id=run_id, settings=settings, options=TrailOptions()))
    second = [e.model_dump(exclude={"created_at"}) for e in repo.get_trail_edges(db, run_id)]
    assert first == second


def test_a_rejected_edge_is_not_recreated_on_a_re_run(db: Session, settings: Settings) -> None:
    run_id = _build_run(db)
    asyncio.run(build_trail(db, run_id=run_id, settings=settings, options=TrailOptions()))
    ds_edge = next(e for e in repo.get_trail_edges(db, run_id) if e.relationship_type == RelationshipType.DATASET_RELATED)
    repo.set_trail_edge_user_state(db, ds_edge.edge_id, UserState.REJECTED)

    asyncio.run(build_trail(db, run_id=run_id, settings=settings, options=TrailOptions()))
    ds_edges = [e for e in repo.get_trail_edges(db, run_id) if e.relationship_type == RelationshipType.DATASET_RELATED]
    assert len(ds_edges) == 1
    assert ds_edges[0].user_state == "rejected"  # still rejected, not resurrected as pending


def test_missing_run_missing_seed_and_missing_ranking_raise(db: Session, settings: Settings) -> None:
    with pytest.raises(RunNotFound):
        asyncio.run(build_trail(db, run_id="nope", settings=settings, options=TrailOptions()))

    db.add(PaperORM(id="pap_np", title="No Profile", title_hash=title_hash("No Profile"), has_full_text=True, source="upload"))
    db.commit()
    repo.create_search_run(db, SearchRun(run_id="run_np", seed_paper_id="pap_np"))
    with pytest.raises(SeedNotReady):
        asyncio.run(build_trail(db, run_id="run_np", settings=settings, options=TrailOptions()))

    _seed(db)
    repo.create_search_run(db, SearchRun(run_id="run_nr", seed_paper_id="pap_seed"))
    with pytest.raises(RankingRequired):
        asyncio.run(build_trail(db, run_id="run_nr", settings=settings, options=TrailOptions()))


def test_provenance_is_persisted_on_every_edge(db: Session, settings: Settings) -> None:
    run_id = _build_run(db)
    asyncio.run(build_trail(db, run_id=run_id, settings=settings, options=TrailOptions()))
    for edge in repo.get_trail_edges(db, run_id):
        assert edge.rule_fired  # WHY the relationship was assigned
        assert "signal_agreement" in edge.confidence_basis
        assert edge.evidence and all(ev.span.quote for ev in edge.evidence)


# --- verbatim evidence (app/services/trail/evidence.py) ----------------------
# Found live: every edge of a real discovery run carried only the target's
# title as its "evidence span". An edge must quote text that shows the link.


def _edge(db: Session, run_id: str, rtype: RelationshipType):
    return next(e for e in repo.get_trail_edges(db, run_id) if e.relationship_type == rtype)


def test_a_foundational_edge_quotes_the_seeds_own_reference_entry(db: Session, settings: Settings) -> None:
    run_id = _build_run(db)
    reference = "[4] V.Karpukhin et al., DensePassageRetrieval for open-domain QA. EMNLP, 2016."
    seed = db.get(PaperORM, "pap_seed")
    assert seed is not None
    seed.references = [{"order": 0, "raw_text": "[1] Unrelated Work on Protein Folding, 2019."}, {"order": 1, "raw_text": reference}]
    db.commit()

    asyncio.run(build_trail(db, run_id=run_id, settings=settings, options=TrailOptions()))
    edge = _edge(db, run_id, RelationshipType.FOUNDATIONAL)
    cited = [ev for ev in edge.evidence if ev.role == "seed_reference"]
    assert len(cited) == 1
    assert cited[0].span.paper_id == "pap_seed"
    assert cited[0].span.section == "References"
    assert cited[0].span.quote == reference
    assert not any(ev.role == "citation" for ev in edge.evidence)  # the title placeholder is gone


def test_a_signal_edge_quotes_a_target_sentence_and_the_seeds_problem(db: Session, settings: Settings) -> None:
    run_id = _build_run(db)
    profile = repo.get_profile(db, "pap_seed")
    assert profile is not None
    problem_span = SourceSpan(paper_id="pap_seed", section="Introduction", quote="knowledge-intensive question answering")
    repo.upsert_profile(
        db,
        profile.model_copy(
            update={"research_problem": ProfileField(value="knowledge intensive question answering", source_span=problem_span)}
        ),
    )
    abstract = (
        "We study generative readers for open-domain systems. "
        "Our reader fuses many retrieved passages for knowledge intensive question answering at scale. "
        "It is fast."
    )
    _add_candidate(
        db, run_id, cand_id="c_sim", title="Fusion-in-Decoder", abstract=abstract, year=2020,
        rel=CitationRelationship.NONE, hops=None, signals=SignalScores(semantic_doc=0.8), rank=4,
    )

    asyncio.run(build_trail(db, run_id=run_id, settings=settings, options=TrailOptions()))
    edge = next(
        e for e in repo.get_trail_edges(db, run_id)
        if e.relationship_type == RelationshipType.SIMILAR and e.target_paper_id != "pap_seed"
        and any(ev.role == "target_claim" for ev in e.evidence)
    )
    target = next(ev for ev in edge.evidence if ev.role == "target_claim")
    assert target.span.section == "Abstract"
    assert target.span.quote == "Our reader fuses many retrieved passages for knowledge intensive question answering at scale."
    assert abstract[target.span.char_start : target.span.char_end] == target.span.quote  # verbatim
    seed_claims = [ev for ev in edge.evidence if ev.role == "seed_claim"]
    assert [ev.span for ev in seed_claims] == [problem_span]
    assert not any(ev.role == "similarity_signal" for ev in edge.evidence)


def test_a_shared_dataset_is_quoted_in_its_sentence(db: Session, settings: Settings) -> None:
    run_id = _build_run(db)
    asyncio.run(build_trail(db, run_id=run_id, settings=settings, options=TrailOptions()))
    edge = _edge(db, run_id, RelationshipType.DATASET_RELATED)
    shared = next(ev for ev in edge.evidence if ev.role == "shared_dataset")
    assert shared.span.quote == "We evaluate on Natural Questions."
    assert shared.span.section == "Abstract"
    assert (shared.span.char_start, shared.span.char_end) == (0, len("We evaluate on Natural Questions."))
