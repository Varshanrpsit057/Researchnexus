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

    def pdf_storage_dir(self) -> Path:
        d = self.data_dir / "papers"
        d.mkdir(parents=True, exist_ok=True)
        return d


def get_settings() -> Settings:
    return Settings()
