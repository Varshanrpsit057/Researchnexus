"""Application settings.

Env-only configuration (no secrets in code), per the global CLAUDE.md rule
and docs/architecture/ResearchNexus_Implementation_Architecture.md §7.
Phase 2 only needs the ingestion-related limits; auth/LLM/BYOK settings are
Phase 1/9 scope and are intentionally not added here.
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

    def pdf_storage_dir(self) -> Path:
        d = self.data_dir / "papers"
        d.mkdir(parents=True, exist_ok=True)
        return d


def get_settings() -> Settings:
    return Settings()
