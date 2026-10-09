"""FastAPI application factory.

Routes: health; sign-up/sign-in/sessions and the account; BYOK model keys;
papers (upload, library, analysis, discovery, ranking, full text); jobs;
workspaces (trail, graph, chat, comparison, gaps, directions, citations,
activity); model usage; the scholarly sources; and, in development only, the
development mailbox. Configuration is checked first (app/startup_checks.py),
then every request passes the request middleware (app/middleware.py).
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.db.session import configure, get_session_factory
from app.jobs.runners import Heartbeat
from app.middleware import RequestMiddleware
from app.routers import (
    auth,
    chat,
    dev,
    health,
    jobs,
    papers,
    service,
    settings_keys,
    synthesis,
    usage,
    workspaces,
)
from app.security import rate_limit
from app.startup_checks import enforce as enforce_config
from app.telemetry.logging import configure_logging, get_logger

_log = get_logger(__name__)


def _on_start(settings: Settings) -> Heartbeat:
    """Jobs run inside the server process that accepted them. Register this
    process as a job runner: its heartbeat lets any server mark a job failed
    once the process running it has stopped (app/jobs/runners.py) -- at
    start, this sweeps up the jobs the last run of this server left behind.
    Then start loading the relevance model in the background (about 4 s
    from cold), so the first discovery run doesn't wait for it (remediation
    Phase 8)."""
    heartbeat = Heartbeat(get_session_factory())
    heartbeat.start()
    if settings.discovery_embedder != "none":
        from app.services.discovery.relevance import relevance_embedder

        threading.Thread(target=relevance_embedder, args=(settings,), name="relevance-model-warmup", daemon=True).start()
    return heartbeat


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level)
    # refuses to start a staging/production server that isn't set up safely
    for finding in enforce_config(settings):
        _log.warning("config_warning", variable=finding.variable, problem=finding.problem)
    configure(settings)
    rate_limit.configure(settings.auth_rate_limit_scale if settings.is_local else 1.0)
    if settings.is_local and settings.auth_rate_limit_scale != 1.0:
        _log.info("auth_rate_limits_scaled", scale=settings.auth_rate_limit_scale)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        heartbeat = _on_start(settings)
        yield
        heartbeat.stop()

    # the interactive API docs only where the API isn't public
    docs = {} if settings.is_local else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="ResearchNexus Backend", version=health.VERSION, lifespan=lifespan, **docs)  # type: ignore[arg-type]
    app.state.settings = settings
    # inside CORS, so its own replies (413, 403, 500) still carry CORS headers
    app.add_middleware(RequestMiddleware, settings=settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Accept", "Content-Type", "X-CSRF-Token", "X-Request-ID"],
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
    if settings.environment == "development" and settings.mail_backend == "console":
        app.include_router(dev.router)
        _log.info("dev_mailbox_enabled", path="/api/v1/dev/mailbox")
    return app


def __getattr__(name: str) -> FastAPI:
    """`app.main:app` (what uvicorn serves) is built on first use, not on
    import: importing this module -- tests do, for create_app -- must never
    open the configured database (in development, the real one)."""
    if name == "app":
        built = create_app()
        globals()["app"] = built
        return built
    raise AttributeError(name)
