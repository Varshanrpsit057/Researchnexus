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

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import configure, get_session_factory
from app.routers import (
    auth,
    chat,
    health,
    jobs,
    papers,
    service,
    settings_keys,
    synthesis,
    usage,
    workspaces,
)
from app.telemetry.logging import configure_logging, get_logger

_log = get_logger(__name__)


def _on_start(settings: Settings) -> None:
    """Jobs run inside this process, so any job still queued or running when
    it starts was cut off by the last one stopping: say so on the job rather
    than leave a page waiting on it forever. Then start loading the relevance
    model in the background (about 4 s from cold), so the first discovery run
    doesn't wait for it (remediation Phase 8)."""
    db = get_session_factory()()
    try:
        interrupted = repo.fail_interrupted_jobs(db)
    finally:
        db.close()
    if interrupted:
        _log.info("interrupted_jobs_failed", count=interrupted)
    if settings.discovery_embedder != "none":
        from app.services.discovery.relevance import relevance_embedder

        threading.Thread(target=relevance_embedder, args=(settings,), name="relevance-model-warmup", daemon=True).start()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    configure(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        _on_start(settings)
        yield

    app = FastAPI(title="ResearchNexus Backend", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # an export's file name (the Word comparison) is read by the page
        expose_headers=["Content-Disposition"],
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
    app.include_router(service.router)
    return app


app = create_app()
