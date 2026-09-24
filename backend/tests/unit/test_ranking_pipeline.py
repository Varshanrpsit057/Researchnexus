from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperORM, SearchRunORM
from app.domain.candidate import (
    CitationRelationship,
    DiscoveryStrategy,
    NormalizedCandidate,
    SearchRun,
)
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.profile import Confidence, ProfileField, ProfileList, ResearchProfile
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.reranker import FakeCrossEncoder
from app.services.normalize.canonical import title_hash
from app.services.ranking.pipeline import (
    RankOptions,
    SearchRunNotFound,
    SeedNotRankable,
    rank_search_run,
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
            authors=["P. Lewis"],
            year=2020,
            abstract="We propose retrieval augmented generation combining parametric and non-parametric memory.",
            has_full_text=True,
            source="upload",
        )
    )
    db.commit()
    repo.save_chunks(
        db,
        [
            PaperChunk(
                chunk_id="chk_1", paper_id="pap_seed", section="Abstract", section_order=0, page=1,
                char_start=0, char_end=40, kind=ChunkKind.ABSTRACT,
                text="retrieval augmented generation parametric non-parametric memory", token_count=7,
            )
        ],
    )
    repo.upsert_profile(
        db,
        ResearchProfile(
            profile_id="prof_seed", paper_id="pap_seed",
            title="Retrieval-Augmented Generation for Knowledge-Intensive NLP",
            abstract="We propose RAG.",
            domain=ProfileField(value="NLP"),
            research_problem=ProfileField(value="knowledge intensive question answering with retrieval"),
            keywords=["retrieval augmented generation"],
            methods=ProfileList(items=[ProfileField(value="dense retrieval")]),
            datasets=ProfileList(items=[ProfileField(value="Natural Questions")]),
            extraction_confidence=Confidence.HIGH,
        ),
    )
    return "pap_seed"


def _run_with_candidates(db: Session, specs: list[dict[str, object]]) -> str:
    seed_id = _seed(db)
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed_id))
    for i, spec in enumerate(specs):
        pid = repo.upsert_discovered_paper(
            db,
            NormalizedCandidate(
                title=str(spec["title"]),
                title_hash=title_hash(str(spec["title"])),
                abstract=spec.get("abstract"),  # type: ignore[arg-type]
                year=spec.get("year"),  # type: ignore[arg-type]
            ),
        )
        repo.add_search_candidate(
            db,
            candidate_id=f"cand_{i}",
            run_id="run_1",
            paper_id=pid,
            discovery_methods=[DiscoveryStrategy.KEYWORD],
            possible_duplicate_of=None,
            provenance={},
            citation_relationship=spec.get("rel", CitationRelationship.NONE),  # type: ignore[arg-type]
            citation_hops=spec.get("hops"),  # type: ignore[arg-type]
        )
    return "run_1"


def _options() -> RankOptions:
    return RankOptions(
        chunk_embedder=FakeEmbeddingProvider(),
        doc_embedder=FakeEmbeddingProvider(),
        reranker=FakeCrossEncoder(),
    )


def test_rank_search_run_persists_a_contiguous_ranking_with_bands_and_explanations(
    db: Session, settings: Settings
) -> None:
    run_id = _run_with_candidates(
        db,
        [
            {"title": "Dense Passage Retrieval", "abstract": "dense retrieval Natural Questions", "year": 2020, "rel": CitationRelationship.CITED_BY_SEED, "hops": 1},
            {"title": "An Unrelated Vision Paper", "abstract": "image classification cnn", "year": 2016},
            {"title": "Fusion-in-Decoder", "abstract": "retrieval augmented generation reader", "year": 2021},
        ],
    )
    result = asyncio.run(rank_search_run(db, run_id=run_id, settings=settings, options=_options()))

    assert result.weights_version == "w0-initial"
    assert result.ranked_count == 3
    assert result.reranked_count == 3  # all within top_n

    ranked = repo.get_ranked_papers(db, run_id)
    assert [r.final_rank for r in ranked] == [1, 2, 3]
    assert all(r.weights_version == "w0-initial" for r in ranked)
    assert all(r.band in {Confidence.HIGH, Confidence.MEDIUM, Confidence.LOW} for r in ranked)
    assert all(r.explanation.bullet_reasons for r in ranked)  # never empty
    # a citation link contributes the `citation` signal only for the cited candidate
    by_cand = {r.candidate_id: r for r in ranked}
    assert by_cand["cand_0"].signals.citation == 1.0
    assert by_cand["cand_1"].signals.citation is None


def test_ranking_is_reproducible(db: Session, settings: Settings) -> None:
    run_id = _run_with_candidates(
        db,
        [
            {"title": "Paper A", "abstract": "retrieval augmented generation", "year": 2022},
            {"title": "Paper B", "abstract": "dense retrieval", "year": 2019},
        ],
    )
    first = asyncio.run(rank_search_run(db, run_id=run_id, settings=settings, options=_options()))
    ranked_1 = repo.get_ranked_papers(db, run_id)
    second = asyncio.run(rank_search_run(db, run_id=run_id, settings=settings, options=_options()))
    ranked_2 = repo.get_ranked_papers(db, run_id)

    assert first.ranked_count == second.ranked_count
    assert ranked_1 == ranked_2  # byte-identical domain output across runs


def test_ranking_without_embedders_still_ranks_on_the_arithmetic_signals(
    db: Session, settings: Settings
) -> None:
    run_id = _run_with_candidates(
        db,
        [
            {"title": "Cited Recent", "abstract": "x", "year": 2026, "rel": CitationRelationship.CITES_SEED, "hops": 1},
            {"title": "Uncited Old", "abstract": "y", "year": 2005},
        ],
    )
    result = asyncio.run(
        rank_search_run(db, run_id=run_id, settings=settings, options=RankOptions(reranker=FakeCrossEncoder()))
    )
    ranked = repo.get_ranked_papers(db, run_id)
    assert result.ranked_count == 2
    # the cited, recent paper outranks the uncited, old one on citation + recency alone
    assert ranked[0].candidate_id == "cand_0"
    assert ranked[0].signals.semantic_doc is None  # no embedder -> similarity signals absent


def test_duplicate_candidate_paper_ids_are_ranked_once(db: Session, settings: Settings) -> None:
    seed_id = _seed(db)
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed_id))
    pid = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Dup", title_hash=title_hash("Dup"), year=2022))
    repo.add_search_candidate(
        db, candidate_id="cand_a", run_id="run_1", paper_id=pid, discovery_methods=[DiscoveryStrategy.KEYWORD],
        possible_duplicate_of=None, provenance={},
    )
    # a second search_candidates row is blocked by UNIQUE(run_id, paper_id); simulate a
    # stale duplicate by adding it under a different run then re-pointing is not possible,
    # so instead assert the pipeline dedupes its own input defensively:
    from app.services.ranking.pipeline import _dedupe_by_paper_id

    keep = _dedupe_by_paper_id(
        [("cand_a", pid), ("cand_b", pid), ("cand_c", "other")]
    )
    assert keep == [("cand_a", pid), ("cand_c", "other")]

    result = asyncio.run(rank_search_run(db, run_id="run_1", settings=settings, options=_options()))
    assert result.ranked_count == 1


def test_missing_run_raises_search_run_not_found(db: Session, settings: Settings) -> None:
    with pytest.raises(SearchRunNotFound):
        asyncio.run(rank_search_run(db, run_id="run_nope", settings=settings, options=_options()))


def test_run_whose_seed_has_no_profile_raises_seed_not_rankable(db: Session, settings: Settings) -> None:
    db.add(
        PaperORM(
            id="pap_noprofile",
            title="A Seed With No Profile",
            title_hash=title_hash("A Seed With No Profile"),
            has_full_text=True,
            source="upload",
        )
    )
    db.commit()
    repo.create_search_run(db, SearchRun(run_id="run_x", seed_paper_id="pap_noprofile"))
    with pytest.raises(SeedNotRankable):
        asyncio.run(rank_search_run(db, run_id="run_x", settings=settings, options=_options()))


class _TopicEmbedder:
    """Two-topic stand-in for a real embedder: text mentioning retrieval
    points one way, anything else the other -- so similarity is 1 or 0."""

    name = "topic-stub"
    dimension = 2

    def __init__(self) -> None:
        self.seen: list[str] = []

    def embed(self, texts: list[str]):  # type: ignore[no-untyped-def]
        import numpy as np

        self.seen.extend(texts)
        return np.array([[1.0, 0.0] if "retrieval" in t.lower() else [0.0, 1.0] for t in texts], dtype="float32")


def test_relevance_floor_sets_off_topic_candidates_aside_and_counts_them(db: Session, settings: Settings) -> None:
    run_id = _run_with_candidates(
        db,
        [
            {"title": "Dense Passage Retrieval for Open-Domain QA", "year": 2020},
            {"title": "Initial sequencing and analysis of the human genome", "year": 2001},
        ],
    )

    db.get(SearchRunORM, run_id).counts = {"raw": 2, "after_dedupe": 2, "after_filter": 2}  # type: ignore[union-attr]
    db.commit()

    embedder = _TopicEmbedder()
    result = asyncio.run(
        rank_search_run(
            db,
            run_id=run_id,
            settings=settings,
            options=RankOptions(chunk_embedder=embedder, doc_embedder=embedder, min_relevance=0.62),
        )
    )

    assert result.ranked_count == 1
    assert result.off_topic_count == 1
    ranked_titles = [c.title for c in repo.get_search_candidates(db, run_id) if c.filter_kept]
    assert ranked_titles == ["Dense Passage Retrieval for Open-Domain QA"]
    genome = next(c for c in repo.get_search_candidates(db, run_id) if "genome" in c.title)
    assert genome.filter_reasons == ["off_topic"]  # set aside with its reason, not deleted
    run = repo.get_search_run(db, run_id)
    assert run is not None
    assert (run.candidate_count_after_filter, run.candidate_count_off_topic) == (1, 1)


def test_seed_is_compared_with_its_profile_abstract_when_the_pdf_had_none(db: Session, settings: Settings) -> None:
    run_id = _run_with_candidates(db, [{"title": "Dense Passage Retrieval", "year": 2020}])
    db.get(PaperORM, "pap_seed").abstract = None  # type: ignore[union-attr]
    db.commit()
    embedder = _TopicEmbedder()
    asyncio.run(
        rank_search_run(db, run_id=run_id, settings=settings, options=RankOptions(doc_embedder=embedder))
    )
    seed_texts = [t for t in embedder.seen if t.startswith("Retrieval-Augmented Generation for Knowledge-Intensive NLP")]
    assert seed_texts == ["Retrieval-Augmented Generation for Knowledge-Intensive NLP\nWe propose RAG."]


def test_without_a_reranker_the_order_is_the_fused_score(db: Session, settings: Settings) -> None:
    run_id = _run_with_candidates(
        db,
        [
            {"title": "A", "year": 2010},
            {"title": "B", "year": 2024, "rel": CitationRelationship.CITES_SEED, "hops": 1},
        ],
    )
    asyncio.run(rank_search_run(db, run_id=run_id, settings=settings, options=RankOptions()))
    ranked = sorted(repo.get_ranked_papers(db, run_id), key=lambda r: r.final_rank)
    assert all(r.rerank_score is None for r in ranked)
    assert [r.fused_score for r in ranked] == sorted((r.fused_score for r in ranked), reverse=True)
