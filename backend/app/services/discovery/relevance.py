"""The relevance model behind discovery and ranking, chosen from settings in
one place, so the discover job and the research orchestrator run with
identical options.

With a real embedder (fastembed's bge-small by default) the ranking scores
every candidate by semantic similarity to the seed and drops the clearly
off-topic ones (`rank_min_relevance`). Without one -- "none", the "fake"
test embedder, or a model that cannot load -- ranking falls back to its
non-semantic signals and no floor is applied, since there is no meaningful
similarity to apply it to.
"""

from __future__ import annotations

from app.config import Settings
from app.domain.ranking import RankingWeights
from app.retrieval.embeddings import EmbeddingProvider, discovery_embedder
from app.services.discovery.pipeline import DiscoveryOptions
from app.services.ranking.pipeline import RankOptions
from app.telemetry.logging import get_logger

_log = get_logger(__name__)


def relevance_embedder(settings: Settings) -> EmbeddingProvider | None:
    embedder = discovery_embedder(settings.discovery_embedder, model_dir=settings.data_dir / "models")
    if embedder is None and settings.discovery_embedder != "none":
        _log.warning("discovery_relevance_model_unavailable", embedder=settings.discovery_embedder)
    return embedder


def discovery_options(embedder: EmbeddingProvider | None) -> DiscoveryOptions:
    return DiscoveryOptions(chunk_embedder=embedder, doc_embedder=embedder)


def rank_options(settings: Settings, embedder: EmbeddingProvider | None, weights: RankingWeights | None = None) -> RankOptions:
    semantic = embedder is not None and embedder.name != "fake"
    return RankOptions(
        weights=weights,
        chunk_embedder=embedder,
        doc_embedder=embedder,
        min_relevance=settings.rank_min_relevance if semantic else None,
    )
