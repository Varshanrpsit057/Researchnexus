"""FastAPI application factory.

Scope: health + auth/session + BYOK settings-keys (Phase 1) + papers
(upload/get) + jobs (get) (Phase 2). Workspaces and every other route in
docs/architecture/ResearchNexus_API_Specification.md belong to later phases
(see docs/architecture/ResearchNexus_Implementation_Roadmap.md) and are not
added speculatively here.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.db.session import configure
from app.routers import auth, health, jobs, papers, settings_keys
from app.telemetry.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    configure(settings)

    app = FastAPI(title="ResearchNexus Backend", version="0.1.0")
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(settings_keys.router)
    app.include_router(papers.router)
    app.include_router(jobs.router)
    return app


app = create_app()
