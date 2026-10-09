"""Application settings.

Env-only configuration (no secrets in code), per the global CLAUDE.md rule
and docs/architecture/ResearchNexus_Implementation_Architecture.md §7.
`secret_key`/`key_vault_secret`/`smtp_password` default to `None` rather
than a placeholder value: nothing here should look like a working secret.
Code that actually needs one raises a typed, clear error when it is unset,
and a staging/production server refuses to start without them
(app/startup_checks.py names what is missing, never a value).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import quote

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RESEARCHNEXUS_", env_file=".env", extra="ignore")

    # Storage
    data_dir: Path = Path("data")
    database_url: str = "sqlite:///./data/researchnexus.db"
    # Or the PostgreSQL connection in parts -- how ECS hands over an RDS
    # database whose password RDS keeps (and rotates) in Secrets Manager.
    # When db_host is set, these build database_url (the password URL-quoted).
    db_host: str | None = None
    db_port: int = 5432
    db_name: str = "researchnexus"
    db_user: str | None = None
    db_password: str | None = None

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

    # Where this server runs. "development" and "test" allow local-only
    # conveniences (plain-HTTP cookies, emails printed to the console, the
    # dev mailbox); "staging" and "production" refuse to start without the
    # settings a public deployment needs (see app/startup_checks.py). The
    # default is "production" so a forgotten setting fails closed: start.py
    # sets "development" for local runs, tests set "test".
    environment: Literal["development", "test", "staging", "production"] = "production"

    # The secret behind one-time codes and the CSRF token (an HMAC key, at
    # least 32 characters). RESEARCHNEXUS_JWT_SECRET is still read, so the
    # local backend/.env made before sessions replaced JWTs keeps working.
    secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("RESEARCHNEXUS_SECRET_KEY", "RESEARCHNEXUS_JWT_SECRET", "secret_key", "jwt_secret"),
    )

    # BYOK key vault (Roadmap Phase 1 / Task 1 item 4): a Fernet key.
    key_vault_secret: str | None = None

    # The address people open the app at (links in emails, the allowed
    # origin of state-changing requests).
    public_app_url: str = "http://localhost:3000"

    # Sessions: an opaque token in an httpOnly cookie, stored only as a hash.
    # A session ends after `session_max_age_hours`, or sooner when unused
    # for `session_idle_hours`.
    session_max_age_hours: int = 336
    session_idle_hours: int = 72
    # Secure cookies (HTTPS only). None = on everywhere but development/test,
    # where the app is served over plain http://localhost.
    cookie_secure: bool | None = None

    # Who may create an account: email domains, e.g. ["university.edu"]
    # (subdomains included). Empty: anyone. Existing accounts are unaffected.
    signup_allowed_domains: list[str] = []

    # One-time codes (sign-up, sign-in, password reset): six digits, valid
    # for `otp_ttl_seconds`, `otp_max_attempts` tries each, a new code at
    # most every `otp_resend_cooldown_seconds`, `otp_max_resends` times.
    otp_ttl_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_max_resends: int = 3

    # Email. "smtp" sends through an SMTP server (Amazon SES's SMTP endpoint
    # in production); "console" prints messages to the server's own output
    # (development only); "memory" keeps them in the process (tests only).
    # None = console in development, memory in test, smtp elsewhere.
    email_backend: Literal["smtp", "console", "memory"] | None = None
    email_from: str | None = None
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_timeout_s: float = 10.0

    # Development only: multiplies every sign-in rate limit (repeated local
    # test runs would otherwise exhaust them). Refused anywhere else
    # (app/startup_checks.py); tests keep the real limits.
    auth_rate_limit_scale: float = 1.0

    # Request bodies other than PDF uploads (JSON) are refused above this.
    max_json_body_kb: int = 1024

    # Logging: "INFO" or "DEBUG" (never prints secrets either way).
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Connection pool for a server database (PostgreSQL); SQLite ignores it.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout_s: float = 10.0
    db_pool_recycle_s: int = 1800
    # Create missing tables at start (development and tests). A deployed
    # database is changed only by `alembic upgrade head`, run as its own
    # deploy step; None = on in development/test, off elsewhere.
    db_auto_create: bool | None = None

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
    # Optional free Semantic Scholar API key (sent as x-api-key, never
    # logged): raises S2's rate limit. Everything works without one.
    semantic_scholar_api_key: str | None = None
    # Optional free OpenAlex API key (sent as "Authorization: Bearer", never
    # logged or put in a URL). Without one, OpenAlex draws on a daily budget
    # shared by everyone on this network's IP address -- a search costs 10
    # credits -- and answers 429 once it is spent (measured 2026-10-01).
    openalex_api_key: str | None = None
    # An address the scholarly sources may contact about this app's traffic:
    # sent to OpenAlex and Crossref in the User-Agent (their faster "polite"
    # access) and, as its API requires, to Unpaywall. Unset: those work
    # anonymously and Unpaywall is skipped.
    contact_email: str | None = None
    # CORE (core.ac.uk), the aggregator of open-access repositories: a free
    # key turns on its search and its full-text copies
    core_api_key: str | None = None
    # look an uploaded paper's record up by its DOI or title (off in tests)
    metadata_lookup: bool = True
    # Full-text retrieval (remediation Phase 7): the time one source may take
    # to answer or start sending a PDF, and how many papers a workspace run
    # reads at once (each source still spaces its own requests).
    fulltext_timeout_s: float = 30.0
    fulltext_concurrency: int = 3
    # look for it by itself when papers join a workspace (off in tests)
    fulltext_auto: bool = True

    # Discovery relevance: the bi-encoder behind the semantic ranking
    # signals. "fastembed" = BAAI/bge-small-en-v1.5 on ONNX (no torch);
    # "fake" = the deterministic hash embedder tests use; "none" = no
    # semantic signals at all. Models are cached under data_dir/models.
    discovery_embedder: str = "fastembed"
    # Candidates whose title+abstract similarity to the seed falls below
    # this are dropped as off-topic (recorded on the candidate, never
    # silently). Calibrated on bge-small: papers Semantic Scholar recommends
    # for a seed scored >= 0.71; clearly unrelated fields scored <= 0.61.
    rank_min_relevance: float = 0.62
    # Where downloaded models live (default: <data_dir>/models). A container
    # image bakes the model in and points this at it.
    models_dir: Path | None = None
    # CPU threads the embedding model may use (None: all cores). Lower it on
    # a small server so embedding doesn't starve request handling. It runs
    # on the GPU only when a GPU build of ONNX Runtime is installed; the log
    # says which provider actually ran ("embedding_model_loaded").
    embedding_threads: int | None = None

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
    # (calibration is Phase 16). Chat and comparison search a workspace with
    # the same real embedder as discovery ("fastembed": bge-small on ONNX;
    # the lexical index if it can't load) -- never the hash stand-in, which
    # only tests use (tests/conftest.py). A cross-encoder reranker is opt-in
    # ("cross-encoder", needs sentence-transformers); "none" keeps the
    # retrieval order.
    rag_retrieve_k: int = 8
    rag_rerank_top_n: int = 5
    # One relevant passage is enough to answer from: the contextual filter
    # has already dropped every chunk it judged irrelevant, and each answer
    # sentence is still checked against the passage it cites. At 2, questions
    # the workspace answers in a single passage were refused.
    rag_min_answerable_chunks: int = 1
    rag_faithfulness_min: float = 0.6
    rag_drop_unsupported: bool = True
    rag_index_cache_size: int = 8
    rag_embedder: str = "fastembed"
    rag_vector_backend: str = "numpy"
    rag_reranker: str = "none"

    # Model per provider, overriding the adapter's default, e.g.
    # RESEARCHNEXUS_LLM_MODELS='{"deepseek": "deepseek-v4-pro"}'.
    llm_models: dict[str, str] = {}

    # Comparison (Roadmap Phase 10 / Architecture §3 S13). `compare_retrieve_k`
    # is the per-paper evidence budget; larger paper sets return a job
    # (async threshold not wired -- see the Phase 10 report).
    compare_retrieve_k: int = 6
    compare_max_sync_papers: int = 4
    # papers a comparison reads at once (each is one model call)
    compare_llm_concurrency: int = 4

    # Research gaps (Roadmap Phase 11 / Architecture §4 GapAnalyzer). The
    # >= 2-supporting-papers bar and the temporal-staleness window are
    # fixed rule thresholds (calibration is Phase 16).
    gap_min_supporting_papers: int = 2
    gap_temporal_years: int = 4
    # How a gap run spends its model calls (remediation Phase 3). Papers
    # without a profile are read, and candidates phrased and checked, this
    # many at a time; each paper and each candidate has its own time limit,
    # so one slow reply can't stall the run. Candidates beyond the per-run
    # cap wait, strongest rules first (see pipeline._priority). The run
    # limit is only a backstop: the work is bounded per item.
    gap_llm_concurrency: int = 6
    gap_profile_timeout_s: float = 120.0
    gap_candidate_timeout_s: float = 90.0
    gap_max_candidates_per_run: int = 40
    gap_run_timeout_s: float = 900.0

    # Research directions (Roadmap Phase 12 / Architecture §4
    # DirectionGenerator). Directions are only ever generated from
    # accepted gaps; this just bounds how many the LLM may propose per gap.
    direction_max_per_gap: int = 2

    # Agentic orchestrator (Roadmap Phase 14 / Architecture §4
    # ResearchOrchestrator). There is no cost setting: with the user's own
    # keys, ResearchNexus can't know what their provider charges, so usage
    # is reported in the provider's own token counts only (remediation
    # Phase 5; app/services/usage/report.py).
    orchestrator_stage_timeout_s: float = 60.0
    # Hard cap on attempts for any single stage call, regardless of what a
    # caller requests -- "no unbounded loops" (Roadmap Phase 14 tests).
    orchestrator_max_stage_attempts: int = 2
    # The "one extra citation hop" bounded decision (Architecture §4):
    # authorise it only when the first discovery pass is this thin.
    orchestrator_min_candidates_for_hop: int = 5
    orchestrator_min_strategy_diversity: int = 2

    # Frontend CORS (Roadmap Phase 15). No frontend existed before this
    # phase, so no CORS policy did either; the dev default is the Next.js
    # dev server's own origin. A real deployment overrides this env-only,
    # same as every other setting here.
    cors_allowed_origins: list[str] = ["http://localhost:3000"]

    @model_validator(mode="after")
    def _database_from_parts(self) -> Settings:
        if self.db_host:
            user = quote(self.db_user or "", safe="")
            password = quote(self.db_password or "", safe="")
            auth = f"{user}:{password}@" if password else f"{user}@" if user else ""
            self.database_url = f"postgresql+psycopg://{auth}{self.db_host}:{self.db_port}/{quote(self.db_name, safe='')}"
        return self

    @property
    def is_local(self) -> bool:
        """development or test: the only places local conveniences exist."""
        return self.environment in ("development", "test")

    @property
    def secure_cookies(self) -> bool:
        return self.cookie_secure if self.cookie_secure is not None else not self.is_local

    @property
    def mail_backend(self) -> str:
        if self.email_backend is not None:
            return self.email_backend
        return {"development": "console", "test": "memory"}.get(self.environment, "smtp")

    @property
    def auto_create_schema(self) -> bool:
        return self.db_auto_create if self.db_auto_create is not None else self.is_local

    def model_cache_dir(self) -> Path:
        return self.models_dir if self.models_dir is not None else self.data_dir / "models"

    def pdf_storage_dir(self) -> Path:
        d = self.data_dir / "papers"
        d.mkdir(parents=True, exist_ok=True)
        return d


def get_settings() -> Settings:
    return Settings()
