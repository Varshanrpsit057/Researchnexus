from __future__ import annotations

import asyncio

import httpx

from app.domain.candidate import CandidateSource, DiscoveryStrategy, RawExternalRecord
from app.domain.chunk import ChunkKind, PaperChunk
from app.external.http import ExternalHttpClient
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.retrieval.faiss_store import NumpyFlatIPIndex
from app.services.discovery.base import DiscoveryFilters, SeedView, StrategyContext, record_key
from app.services.discovery.budget import DiscoveryBudget
from app.services.discovery.semantic import SemanticChunkStrategy
from app.services.discovery.semantic_doc import SpecterDocStrategy


def _chunk(text: str, i: int) -> PaperChunk:
    return PaperChunk(
        chunk_id=f"chk_{i}",
        paper_id="pap_seed",
        section="Abstract",
        section_order=0,
        page=1,
        char_start=i * 100,
        char_end=i * 100 + len(text),
        kind=ChunkKind.ABSTRACT,
        text=text,
        token_count=len(text.split()),
    )


def _rec(title: str, abstract: str, doi: str) -> RawExternalRecord:
    return RawExternalRecord(source=CandidateSource.OPENALEX, doi=doi, title=title, abstract=abstract)


def _ctx(pool: list[RawExternalRecord], *, with_embedder: bool = True, seed_chunks: list[PaperChunk] | None = None) -> StrategyContext:
    ctx = StrategyContext(
        seed=SeedView(paper_id="pap_seed", title="Seed Paper", abstract="retrieval augmented generation"),
        seed_chunks=seed_chunks if seed_chunks is not None else [_chunk("retrieval augmented generation", 0)],
        plan=__import__("app.domain.candidate", fromlist=["SearchPlan"]).SearchPlan(),
        filters=DiscoveryFilters(max_results_per_strategy=5),
        budget=DiscoveryBudget(),
        http=ExternalHttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))),
        chunk_embedder=FakeEmbeddingProvider() if with_embedder else None,
        doc_embedder=FakeEmbeddingProvider() if with_embedder else None,
    )
    ctx.candidate_pool = pool
    return ctx


def test_semantic_chunk_scores_the_pool_and_retags_it() -> None:
    pool = [_rec("Dense Retrieval", "dense retrieval for qa", "10.1/a"), _rec("Unrelated", "quantum chromodynamics", "10.1/b")]
    result = asyncio.run(SemanticChunkStrategy().run(_ctx(pool)))
    assert result.strategy == DiscoveryStrategy.SEMANTIC
    assert {r.doi for r in result.records} == {"10.1/a", "10.1/b"}
    for key, sig in result.signals.items():
        assert -1.0 <= sig["semantic_score"] <= 1.0
        assert key


def test_semantic_doc_uses_doc_embedder_and_its_own_signal_field() -> None:
    pool = [_rec("Dense Retrieval", "dense retrieval for qa", "10.1/a")]
    result = asyncio.run(SpecterDocStrategy().run(_ctx(pool)))
    assert result.strategy == DiscoveryStrategy.SEMANTIC_DOC
    key = record_key(pool[0])
    assert "semantic_doc_score" in result.signals[key]


def test_semantic_strategy_is_empty_without_an_embedder() -> None:
    result = asyncio.run(SemanticChunkStrategy().run(_ctx([_rec("X", "y", "10.1/a")], with_embedder=False)))
    assert result.records == []
    assert "semantic_no_embedder" in result.notes


def test_semantic_strategy_is_empty_with_an_empty_pool_and_no_corpus() -> None:
    result = asyncio.run(SemanticChunkStrategy().run(_ctx([])))
    assert result.records == []


def test_semantic_strategy_retrieves_new_papers_from_an_injected_corpus_index() -> None:
    embedder = FakeEmbeddingProvider()
    corpus_records = {
        "c1": _rec("Corpus Paper on Retrieval", "retrieval augmented generation methods", "10.9/c1"),
        "c2": _rec("Corpus Paper on Vision", "image classification with cnns", "10.9/c2"),
    }
    index = NumpyFlatIPIndex(dimension=embedder.dimension)
    texts = [f"{r.title}\n{r.abstract}" for r in corpus_records.values()]
    index.add(list(corpus_records), embedder.embed(texts))

    strat = SemanticChunkStrategy(corpus_index=index, corpus_records=corpus_records)
    result = asyncio.run(strat.run(_ctx([])))  # empty pool -> only corpus hits
    found = {r.doi for r in result.records}
    assert "10.9/c1" in found  # the retrieval paper is surfaced from the corpus
