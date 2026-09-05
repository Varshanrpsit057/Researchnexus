"""Database engine/session setup.

SQLite for local/dev/test (Roadmap: "PostgreSQL for research/prod" comes
later, Data Model §15). FK enforcement is off by default in SQLite, so it
is turned on per-connection.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.base import Base


def make_engine(settings: Settings) -> Engine:
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=connect_args)

    if settings.database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def configure(settings: Settings) -> None:
    """Idempotent app-startup wiring; safe to call once from app.main."""
    global _engine, _SessionFactory
    if settings.database_url.startswith("sqlite:///"):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
    _engine = make_engine(settings)
    init_db(_engine)
    _SessionFactory = make_session_factory(_engine)


def get_session_factory() -> sessionmaker[Session]:
    if _SessionFactory is None:
        raise RuntimeError("database not configured; call app.db.session.configure(settings) first")
    return _SessionFactory


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency. Call `configure(settings)` once at startup first."""
    if _SessionFactory is None:
        raise RuntimeError("database not configured; call app.db.session.configure(settings) first")
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()
