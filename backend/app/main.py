"""FastAPI application factory.

Phase 2 scope: health + papers (upload/get) + jobs (get). Auth, BYOK keys,
workspaces and every other route in docs/architecture/
ResearchNexus_API_Specification.md belong to later phases (see docs/
architecture/ResearchNexus_Implementation_Roadmap.md) and are not added
speculatively here.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.db.session import configure
from app.routers import health, jobs, papers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure(settings)

    app = FastAPI(title="ResearchNexus Backend", version="0.1.0")
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(papers.router)
    app.include_router(jobs.router)
    return app


app = create_app()
