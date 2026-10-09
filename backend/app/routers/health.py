"""Health endpoints, kept apart so a load balancer asks the right question:

- /health/live: the process is up and serving. Nothing else -- a database
  outage must not get a healthy container killed and restarted in a loop.
- /health/ready: this instance can do its work: the database answers, its
  schema is the one this code expects (deployed: `alembic upgrade head` has
  run), and the file store is writable. 503 when not, so the load balancer
  sends no traffic until it is.
- /health/providers: how the optional outside services are set up (and,
  from a check at most every ten minutes, how they answered). Always 200:
  an unavailable research API degrades a feature, not the app.
- /health: the original summary (status + database), kept for old clients.
"""

from __future__ import annotations

import asyncio
import time
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from app.config import Settings
from app.deps import AppSettings, DbSession

router = APIRouter(tags=["health"])

VERSION = "0.2.0"
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_PROVIDER_CHECK_EVERY_S = 600.0
_provider_state: dict[str, object] = {"checked_at": None, "results": [], "running": False}


@lru_cache(maxsize=1)
def expected_revision() -> str | None:
    """The newest migration this code ships with (None if they aren't
    shipped alongside, e.g. a trimmed image)."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
        return ScriptDirectory.from_config(cfg).get_current_head()
    except Exception:  # noqa: BLE001 - reported as "unknown", never raised
        return None


def _database(db: DbSession) -> str:
    try:
        db.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001 - reported, not raised: health must answer
        db.rollback()
        return "error"


def _schema(db: DbSession, settings: Settings) -> str:
    if settings.auto_create_schema:
        return "ok"  # development/tests make missing tables themselves
    try:
        from alembic.runtime.migration import MigrationContext

        current = MigrationContext.configure(db.connection()).get_current_revision()
    except Exception:  # noqa: BLE001
        db.rollback()
        return "error"
    head = expected_revision()
    if head is None:
        return "unknown"
    return "ok" if current == head else "migration_pending"


def _storage(settings: Settings) -> str:
    try:
        target = settings.pdf_storage_dir() / ".ready-check"
        target.write_bytes(b"ok")
        target.unlink(missing_ok=True)
        return "ok"
    except OSError:
        return "error"


@router.get("/health")
def health(db: DbSession) -> dict[str, object]:
    # API spec §2: a status plus the checks behind it, so a client can tell what is down
    database = _database(db)
    return {"status": "ok" if database == "ok" else "degraded", "version": VERSION, "checks": {"db": database}}


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
def ready(db: DbSession, settings: AppSettings, response: Response) -> dict[str, object]:
    checks = {"database": _database(db)}
    checks["schema"] = _schema(db, settings) if checks["database"] == "ok" else "unknown"
    checks["storage"] = _storage(settings)
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "unavailable", "version": VERSION, "environment": settings.environment, "checks": checks}


async def _refresh_providers(settings: Settings) -> None:
    from app.services.sources import check_sources

    try:
        _provider_state["results"] = await check_sources(settings)
        _provider_state["checked_at"] = time.time()
    finally:
        _provider_state["running"] = False


@router.get("/health/providers")
async def providers(request: Request, settings: AppSettings) -> dict[str, object]:
    from app.services.sources import describe_sources

    checked_at = _provider_state["checked_at"]
    stale = checked_at is None or time.time() - float(checked_at) > _PROVIDER_CHECK_EVERY_S  # type: ignore[arg-type]
    if stale and not _provider_state["running"]:
        # one check at a time, in the background: this reply never waits on the outside world
        _provider_state["running"] = True
        task = asyncio.get_running_loop().create_task(_refresh_providers(settings))
        request.app.state.provider_check = task  # keep a reference until it's done
    return {
        "status": "ok",
        "email": {"backend": settings.mail_backend, "configured": settings.mail_backend != "smtp" or bool(settings.smtp_host and settings.email_from)},
        "sources": describe_sources(settings),
        "last_check": {"checked_at": checked_at, "results": _provider_state["results"]},
    }
