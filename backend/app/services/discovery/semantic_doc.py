"""Semantic (document-level, SPECTER2) discovery (Architecture §3 S6; Data
Model §3 `semantic_doc_score`). Same machinery as
`app/services/discovery/semantic.py` but a single seed vector (SPECTER2 of
title + abstract) and its own signal field. The full method/topic/RQ
embedding "views" (the other 3 of the 7 strategies) are deferred -- the
Roadmap MVP note allows them to be `semantic_doc` re-uses initially.
"""

from __future__ import annotations

from app.domain.candidate import DiscoveryStrategy
from app.retrieval.embeddings import EmbeddingProvider
from app.services.discovery.base import StrategyContext
from app.services.discovery.semantic import _SemanticStrategyBase


class SpecterDocStrategy(_SemanticStrategyBase):
    strategy = DiscoveryStrategy.SEMANTIC_DOC
    signal_field = "semantic_doc_score"

    def _embedder(self, ctx: StrategyContext) -> EmbeddingProvider | None:
        return ctx.doc_embedder

    def seed_texts(self, ctx: StrategyContext) -> list[str]:
        combined = f"{ctx.seed.title}\n{ctx.seed.abstract or ''}".strip()
        return [combined] if combined else []
