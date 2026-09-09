"""Semantic (chunk-level) discovery (Architecture §3 S6; Data Model §3
`semantic_score`).

MVP behaviour: there is no pre-built corpus index yet
(`scripts/build_corpus_index.py` is deferred), so this strategy's default
job is to **re-score the pool** the lexical/citation strategies produced --
it embeds the seed's chunks (MiniLM in prod, `FakeEmbeddingProvider` in
tests) and every pooled candidate's title+abstract, and attaches
`semantic_score = max cosine(seed chunk, candidate)` per candidate. If a
corpus index *is* injected it is queried too, adding genuinely new
candidates. Returns empty (with a note) when no embedder or nothing to
score -- the runner treats that as a normal outcome.
"""

from __future__ import annotations

import numpy as np

from app.domain.candidate import DiscoveryStrategy, RawExternalRecord
from app.retrieval.embeddings import EmbeddingProvider
from app.retrieval.faiss_store import VectorIndex
from app.services.discovery.base import StrategyContext, StrategyResult, record_key


def _l2norm(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype="float32")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0.0, 1.0, norms)


class _SemanticStrategyBase:
    strategy: DiscoveryStrategy
    signal_field: str

    def __init__(
        self,
        *,
        corpus_index: VectorIndex | None = None,
        corpus_records: dict[str, RawExternalRecord] | None = None,
    ) -> None:
        self._corpus_index = corpus_index
        self._corpus_records = corpus_records or {}

    def _embedder(self, ctx: StrategyContext) -> EmbeddingProvider | None:  # pragma: no cover - overridden
        raise NotImplementedError

    def _seed_texts(self, ctx: StrategyContext) -> list[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    async def run(self, ctx: StrategyContext) -> StrategyResult:
        result = StrategyResult(strategy=self.strategy)
        embedder = self._embedder(ctx)
        if embedder is None:
            result.notes.append(f"{self.strategy.value}_no_embedder")
            return result
        seed_texts = [t for t in self._seed_texts(ctx) if t.strip()]
        if not seed_texts:
            result.notes.append(f"{self.strategy.value}_no_seed_text")
            return result

        seed_vecs = _l2norm(embedder.embed(seed_texts))

        pool = list(ctx.candidate_pool)
        if pool:
            cand_vecs = _l2norm(embedder.embed([f"{r.title}\n{r.abstract or ''}" for r in pool]))
            sims = cand_vecs @ seed_vecs.T  # (num_candidates, num_seed_texts)
            for rec, row in zip(pool, sims, strict=True):
                key = record_key(rec)
                result.records.append(rec)
                result.signals[key] = {self.signal_field: round(float(row.max()), 4)}

        if self._corpus_index is not None and self._corpus_index.size() > 0:
            self._query_corpus(ctx, result, seed_vecs)

        if not result.records:
            result.notes.append(f"{self.strategy.value}_nothing_to_score")
        return result

    def _query_corpus(self, ctx: StrategyContext, result: StrategyResult, seed_vecs: np.ndarray) -> None:
        assert self._corpus_index is not None
        best: dict[str, float] = {}
        for qv in seed_vecs:
            for cid, score in self._corpus_index.search(qv, ctx.filters.max_results_per_strategy):
                best[cid] = max(best.get(cid, -1.0), float(score))
        for cid, score in best.items():
            rec = self._corpus_records.get(cid)
            if rec is None:
                continue
            key = record_key(rec)
            if key not in result.signals:
                result.records.append(rec)
            prev = result.signals.get(key, {}).get(self.signal_field, -1.0)
            result.signals[key] = {self.signal_field: round(max(prev, score), 4)}


class SemanticChunkStrategy(_SemanticStrategyBase):
    strategy = DiscoveryStrategy.SEMANTIC
    signal_field = "semantic_score"

    def _embedder(self, ctx: StrategyContext) -> EmbeddingProvider | None:
        return ctx.chunk_embedder

    def _seed_texts(self, ctx: StrategyContext) -> list[str]:
        texts = [c.text for c in ctx.seed_chunks]
        if not texts and ctx.seed.abstract:
            texts = [ctx.seed.abstract]
        return texts
