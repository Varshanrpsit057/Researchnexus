"""Stage S9-S10 orchestration: take a completed SearchRun's candidates and
produce a persisted ranking (Roadmap Phase 6).

Fully deterministic given deterministic embedders/reranker (the defaults in
tests). Fusion, rerank, ordering, banding and the bullet explanations are
arithmetic; the only optional LLM touch is `add_llm_prose` on the top-K
prose strings, and it can never change `bullet_reasons` or the ordering.
`weights_version` is stamped on every row for provenance and reproducibility
(Evaluation Plan §3 "Determinism").

Synchronous library call -- the full `GET /papers/{id}/related` response
(pagination, band/type filters) is deferred like the P5 discover endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.profile import Confidence
from app.domain.ranking import RankedPaper, RankingWeights, SignalScores
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.reranker import CrossEncoderReranker
from app.services.metadata.publishers import preferred_set, publisher_of
from app.services.ranking.explain import add_llm_prose, build_explanation
from app.services.ranking.fuse import fuse
from app.services.ranking.rerank import rerank_scores
from app.services.ranking.signals import (
    citation_signal,
    dataset_overlap_signal,
    method_sim_signal,
    problem_sim_signal,
    publisher_signal,
    recency_signal,
    semantic_chunk_signal,
    semantic_doc_signal,
)

try:  # pragma: no cover - imported only for a type hint
    from app.llm.session import LlmSession
except Exception:  # pragma: no cover
    LlmSession = object  # type: ignore[assignment,misc]


class SearchRunNotFound(Exception):
    pass


class SeedNotRankable(Exception):
    """The run's seed paper or its ResearchProfile is missing."""


@dataclass
class RankOptions:
    weights: RankingWeights | None = None
    chunk_embedder: EmbeddingProvider | None = None
    doc_embedder: EmbeddingProvider | None = None
    # Optional cross-encoder rerank of the top slice; None orders by the fused
    # score alone. MS MARCO cross-encoders judge query->passage relevance, and
    # on real seeds they misjudged paper-to-paper similarity (an on-topic
    # paper scored 0.003, an off-topic one 0.87), so production passes none.
    reranker: CrossEncoderReranker | None = None
    # Candidates whose `semantic_doc` similarity to the seed is below this are
    # dropped as off-topic -- recorded on the candidate, never silently. None
    # keeps everything: right for the deterministic fake embedders, whose
    # similarities mean nothing.
    min_relevance: float | None = None
    session: object | None = None  # LlmSession | None -- optional prose rephrase
    # the publishers the reader prefers, as `publishers.preferred_set` names
    # them; None ranks with the default four (remediation, 2026-10-06)
    preferred_publishers: tuple[str, ...] | None = None


@dataclass
class RankResult:
    run_id: str
    weights_version: str
    ranked_count: int
    reranked_count: int
    off_topic_count: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Scored:
    candidate_id: str
    paper_id: str
    text: str
    signals: SignalScores
    fused_score: float
    rerank_score: float | None = None

    @property
    def tie_key(self) -> tuple[str, str]:
        """Equal scores are ordered by the paper itself (title, then id) --
        never by candidate id, which says nothing about the paper -- so the
        same candidates always rank the same (remediation Phase 8)."""
        return (self.text.casefold(), self.paper_id)


def _dedupe_by_paper_id(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen: set[str] = set()
    keep: list[tuple[str, str]] = []
    for cid, pid in pairs:
        if pid in seen:
            continue
        seen.add(pid)
        keep.append((cid, pid))
    return keep


def _embed_one(embedder: EmbeddingProvider | None, text: str) -> np.ndarray | None:
    if embedder is None or not text.strip():
        return None
    return np.asarray(embedder.embed([text])[0], dtype="float32")


def _embed_many(embedder: EmbeddingProvider | None, texts: list[str]) -> np.ndarray | None:
    clean = [t for t in texts if t.strip()]
    if embedder is None or not clean:
        return None
    return np.asarray(embedder.embed(clean), dtype="float32")


def _embed_aligned(embedder: EmbeddingProvider | None, texts: list[str]) -> np.ndarray | None:
    """One batch call with rows aligned to `texts` (none is blank: every
    candidate has a title)."""
    if embedder is None or not texts:
        return None
    return np.asarray(embedder.embed(texts), dtype="float32")


def _publisher_of(db: Session, paper_id: str) -> str | None:
    paper = repo.get_paper(db, paper_id)
    if paper is None:
        return None
    return paper.publisher or publisher_of(None, paper.doi)


def _band(score: float, settings: Settings) -> Confidence:
    if score >= settings.rank_band_high:
        return Confidence.HIGH
    if score >= settings.rank_band_medium:
        return Confidence.MEDIUM
    return Confidence.LOW


async def rank_search_run(
    db: Session,
    *,
    run_id: str,
    settings: Settings,
    options: RankOptions,
) -> RankResult:
    run = repo.get_search_run(db, run_id)
    if run is None:
        raise SearchRunNotFound(run_id)
    seed = repo.get_paper(db, run.seed_paper_id)
    profile = repo.get_profile(db, run.seed_paper_id)
    if seed is None or profile is None:
        raise SeedNotRankable(run.seed_paper_id)

    seed_chunks = repo.get_chunks_for_paper(db, run.seed_paper_id)
    candidates = repo.get_search_candidates(db, run_id)
    paper_ids = repo.get_search_candidate_paper_ids(db, run_id)

    kept = _dedupe_by_paper_id([(c.candidate_id, paper_ids[c.candidate_id]) for c in candidates])
    kept_ids = {cid for cid, _ in kept}
    candidates = [c for c in candidates if c.candidate_id in kept_ids]

    weights = options.weights or RankingWeights()
    current_year = run.started_at.year
    preferred = preferred_set(options.preferred_publishers)
    repo.set_run_preferred_publishers(db, run_id, preferred)

    # the parser often misses a PDF's abstract; the profile then holds it
    seed_text = f"{seed.title}\n{seed.abstract or profile.abstract or ''}"
    seed_doc_vec = _embed_one(options.doc_embedder, seed_text)
    seed_chunk_vecs = _embed_many(options.chunk_embedder, [ch.text for ch in seed_chunks])
    problem_vec = _embed_one(options.chunk_embedder, profile.research_problem.value)
    method_text = "; ".join(i.value for i in profile.methods.items)
    method_vec = _embed_one(options.chunk_embedder, method_text)
    dataset_names = [i.value for i in profile.datasets.items if i.value.strip()]

    cand_texts = [f"{cand.title}\n{cand.abstract or ''}" for cand in candidates]
    cand_doc_vecs = _embed_aligned(options.doc_embedder, cand_texts)
    cand_chunk_vecs = _embed_aligned(options.chunk_embedder, cand_texts)

    scored: list[_Scored] = []
    off_topic: list[str] = []
    for idx, cand in enumerate(candidates):
        cand_text = cand_texts[idx]
        cand_doc_vec = cand_doc_vecs[idx] if cand_doc_vecs is not None else None
        cand_vec = cand_chunk_vecs[idx] if cand_chunk_vecs is not None else None
        signals = SignalScores(
            semantic_doc=semantic_doc_signal(seed_doc_vec, cand_doc_vec),
            semantic_chunk=semantic_chunk_signal(seed_chunk_vecs, cand_vec),
            problem_sim=problem_sim_signal(problem_vec, cand_vec),
            method_sim=method_sim_signal(method_vec, cand_vec),
            dataset_overlap=dataset_overlap_signal(dataset_names, cand_text),
            citation=citation_signal(cand.citation_relationship, cand.citation_hops),
            recency=recency_signal(cand.year, current_year, half_life_years=settings.rank_recency_half_life_years),
            publisher=publisher_signal(_publisher_of(db, paper_ids[cand.candidate_id]), preferred),
        )
        if options.min_relevance is not None and signals.semantic_doc is not None and signals.semantic_doc < options.min_relevance:
            off_topic.append(cand.candidate_id)
            continue
        fused = fuse(signals, weights).fused_score
        scored.append(
            _Scored(cand.candidate_id, paper_ids[cand.candidate_id], cand_text, signals, fused)
        )

    scored.sort(key=lambda s: (-s.fused_score, s.tie_key))

    rr: dict[str, float] = {}
    if options.reranker is not None:
        rr = rerank_scores(seed_text, [(s.candidate_id, s.text) for s in scored], options.reranker, settings.rank_rerank_top_n)
    for s in scored:
        s.rerank_score = rr.get(s.candidate_id)

    ranked = await _order_and_explain(scored, weights, settings, session=options.session)
    repo.save_ranked_papers(db, run_id, ranked, {s.candidate_id: s.paper_id for s in scored})
    repo.mark_candidates_off_topic(db, run_id, off_topic)
    return RankResult(
        run_id=run_id,
        weights_version=weights.version,
        ranked_count=len(ranked),
        reranked_count=len(rr),
        off_topic_count=len(off_topic),
    )


async def _order_and_explain(
    scored: list[_Scored], weights: RankingWeights, settings: Settings, *, session: object | None = None
) -> list[RankedPaper]:
    """The final order -- by fused score, the reranked head first when a
    reranker scored it, ties broken by the paper itself -- each paper banded
    and explained by what its signals contributed. Shared by a full ranking
    and a re-rank of a saved one, so the two can never order differently."""
    scored = sorted(scored, key=lambda s: (-s.fused_score, s.tie_key))
    top_n = settings.rank_rerank_top_n
    head, tail = scored[:top_n], scored[top_n:]
    head.sort(
        key=lambda s: (
            -(s.rerank_score if s.rerank_score is not None else -1.0),
            -s.fused_score,
            s.tie_key,
        )
    )
    ranked: list[RankedPaper] = []
    for position, s in enumerate(head + tail, start=1):
        final_score = s.rerank_score if s.rerank_score is not None else s.fused_score
        explanation = build_explanation(
            s.signals, threshold=settings.rank_explanation_threshold, fusion=fuse(s.signals, weights)
        )
        if session is not None and position <= settings.rank_llm_prose_top_k:
            explanation = await add_llm_prose(explanation, session=session)  # type: ignore[arg-type]
        ranked.append(
            RankedPaper(
                candidate_id=s.candidate_id,
                signals=s.signals,
                weights_version=weights.version,
                fused_score=s.fused_score,
                rerank_score=s.rerank_score,
                final_rank=position,
                band=_band(final_score, settings),
                explanation=explanation,
            )
        )
    return ranked


class RankingRequired(Exception):
    """The run has no ranking to re-weigh yet."""


async def rerank_with_weights(
    db: Session,
    *,
    run_id: str,
    weights: RankingWeights,
    settings: Settings,
    preferred_publishers: tuple[str, ...] | None = None,
) -> RankResult:
    """Re-weigh a saved ranking (remediation Phase 9). A paper's signals don't
    depend on the weights, so its saved signals are fused again -- no search,
    no embedding, nothing recomputed but the arithmetic -- and the papers are
    ordered exactly as a full ranking with these weights would order them.
    Papers set aside as off-topic stay aside: the relevance floor isn't a weight.
    Given `preferred_publishers`, the publisher signal is read again from each
    paper's record against them (a lookup, not a search); without it, the
    run keeps the publishers it was ranked with."""
    if repo.get_search_run(db, run_id) is None:
        raise SearchRunNotFound(run_id)
    saved = repo.get_ranked_papers(db, run_id)
    if not saved:
        raise RankingRequired(run_id)
    candidates = {c.candidate_id: c for c in repo.get_search_candidates(db, run_id)}
    paper_ids = repo.get_search_candidate_paper_ids(db, run_id)
    if preferred_publishers is not None:
        repo.set_run_preferred_publishers(db, run_id, preferred_publishers)
    scored = []
    for rp in saved:
        if rp.candidate_id not in candidates:
            continue
        # new preferred publishers, or a ranking saved before the publisher
        # signal existed: the signal comes from the paper's record
        signals = (
            rp.signals
            if preferred_publishers is None and rp.signals.publisher is not None
            else rp.signals.model_copy(
                update={"publisher": publisher_signal(_publisher_of(db, paper_ids[rp.candidate_id]), preferred_publishers)}
            )
        )
        scored.append(
            _Scored(
                rp.candidate_id,
                paper_ids[rp.candidate_id],
                f"{candidates[rp.candidate_id].title}\n{candidates[rp.candidate_id].abstract or ''}",
                signals,
                fuse(signals, weights).fused_score,
                rp.rerank_score,
            )
        )
    ranked = await _order_and_explain(scored, weights, settings)
    repo.save_ranked_papers(db, run_id, ranked, {s.candidate_id: s.paper_id for s in scored})
    return RankResult(
        run_id=run_id,
        weights_version=weights.version,
        ranked_count=len(ranked),
        reranked_count=sum(1 for s in scored if s.rerank_score is not None),
    )
