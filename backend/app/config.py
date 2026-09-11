"""Application settings.

Env-only configuration (no secrets in code), per the global CLAUDE.md rule
and docs/architecture/ResearchNexus_Implementation_Architecture.md §7.
`jwt_secret`/`key_vault_secret` default to `None` rather than a placeholder
value: nothing here should look like a working secret. Code that actually
needs one (app/security/jwt.py, app/security/key_vault.py) raises a typed,
clear error when it is unset, the same lazy-optional pattern already used
for the embeddings/FAISS backends in app/retrieval/*.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESEARCHNEXUS_", env_file=".env", extra="ignore")

    # Storage
    data_dir: Path = Path("data")
    database_url: str = "sqlite:///./data/researchnexus.db"

    # Upload validation (Architecture §3 Stage S1; API spec §Errors 413/415/422)
    max_pdf_mb: int = 30
    max_pages: int = 60
    # Decompression-ratio / "zip-bomb" guard (Architecture §3 S2 failure handling):
    # a single page yielding more raw characters than this is treated as
    # suspicious and truncated rather than processed in full.
    max_page_chars: int = 500_000

    # Chunking (Architecture §3 S3 / Data Model §6)
    chunk_target_tokens: int = 750
    chunk_overlap_tokens: int = 100

    # Auth (Roadmap Phase 1 / Task 1 item 2-3): dev JWT signing.
    jwt_secret: str | None = None
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 1440

    # BYOK key vault (Roadmap Phase 1 / Task 1 item 4): a Fernet key.
    key_vault_secret: str | None = None

    # ResearchProfile extraction (Roadmap Phase 3 / Architecture §3 S4): a
    # char budget standing in for a token budget on the LLM prompt, same
    # "no tokenizer dependency" rationale as chunk_target_tokens above.
    profile_max_context_chars: int = 20_000

    # External scholarly APIs (Roadmap Phase 4 / Architecture §1.1 row H):
    # resilience knobs for the arXiv/OpenAlex/S2/Crossref clients.
    external_timeout_s: float = 15.0
    external_max_retries: int = 3
    external_backoff_base_s: float = 0.5
    external_cache_ttl_s: float = 300.0

    # Ranking (Roadmap Phase 6 / Architecture §3 S9-S10 / Data Model §4).
    # Band cutoffs and the recency half-life are fixed "w0" values -- their
    # calibration is Phase 16's job (Evaluation Plan §3), same as the
    # RankingWeights themselves.
    rank_rerank_top_n: int = 50
    rank_band_high: float = 0.66
    rank_band_medium: float = 0.33
    rank_explanation_threshold: float = 0.5
    rank_recency_half_life_years: float = 4.0
    rank_llm_prose_top_k: int = 10

    # Typed research trail (Roadmap Phase 7 / Architecture §3 S11). Rule
    # thresholds live in app/services/trail/rules.py::TrailThresholds as
    # fixed "w0" values (calibration is Phase 16); only the run-scoped caps
    # are surfaced here.
    trail_top_k: int = 40
    trail_max_seed_claims: int = 3

    # RAG + citations (Roadmap Phase 9 / Architecture §3 S13). Retrieval /
    # rerank widths and the faithfulness floor are fixed "w0" values
    # (calibration is Phase 16). The real MiniLM embedder, a faiss vector
    # backend and the cross-encoder reranker are opt-in -- the defaults are
    # the deterministic, dependency-free stand-ins so tests stay hermetic.
    rag_retrieve_k: int = 8
    rag_rerank_top_n: int = 5
    rag_min_answerable_chunks: int = 2
    rag_faithfulness_min: float = 0.6
    rag_drop_unsupported: bool = True
    rag_index_cache_size: int = 8
    rag_embedder: str = "fake"
    rag_vector_backend: str = "numpy"
    rag_reranker: str = "fake"

    # Comparison (Roadmap Phase 10 / Architecture §3 S13). `compare_retrieve_k`
    # is the per-paper evidence budget; larger paper sets return a job
    # (async threshold not wired -- see the Phase 10 report).
    compare_retrieve_k: int = 6
    compare_max_sync_papers: int = 4

    # Research gaps (Roadmap Phase 11 / Architecture §4 GapAnalyzer). The
    # >= 2-supporting-papers bar and the temporal-staleness window are
    # fixed rule thresholds (calibration is Phase 16).
    gap_min_supporting_papers: int = 2
    gap_temporal_years: int = 4

    def pdf_storage_dir(self) -> Path:
        d = self.data_dir / "papers"
        d.mkdir(parents=True, exist_ok=True)
        return d


def get_settings() -> Settings:
    return Settings()
