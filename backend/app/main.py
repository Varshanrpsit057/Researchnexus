"""FastAPI application factory.

Scope: health + auth/session + BYOK settings-keys (Phase 1) + papers
(upload/get/analyze/profile) + jobs (get) (Phases 2-3) + workspaces
(CRUD + papers + trail review) (Phase 8) + chat/RAG and synthesis
(summary/keypoints/citations) (Phase 9). Every other route in
docs/architecture/ResearchNexus_API_Specification.md belongs to later
phases (see docs/architecture/ResearchNexus_Implementation_Roadmap.md)
and is not added speculatively here.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db.session import configure
from app.routers import (
    auth,
    chat,
    health,
    jobs,
    papers,
    settings_keys,
    synthesis,
    usage,
    workspaces,
)
from app.telemetry.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    configure(settings)

    app = FastAPI(title="ResearchNexus Backend", version="0.1.0")
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(settings_keys.router)
    app.include_router(papers.router)
    app.include_router(jobs.router)
    app.include_router(workspaces.router)
    app.include_router(chat.router)
    app.include_router(synthesis.router)
    app.include_router(usage.router)
    return app


app = create_app()
