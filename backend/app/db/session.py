"""Database engine/session setup.

SQLite for local development and tests; PostgreSQL (psycopg 3) for staging
and production. FK enforcement is off by default in SQLite, so it is turned
on per-connection. A server database gets a bounded connection pool whose
connections are checked before use (a database restart or failover leaves
dead ones behind) and recycled every half hour.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.base import Base


def make_engine(settings: Settings) -> Engine:
    if settings.database_url.startswith("sqlite"):
        # a writer waits up to 15 s for another writer before giving up
        engine = create_engine(settings.database_url, connect_args={"check_same_thread": False, "timeout": 15})
    else:
        engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_s,
            pool_recycle=settings.db_pool_recycle_s,
            pool_pre_ping=True,
            # a request never waits more than 10 s to connect; a statement is
            # cancelled after 60 s rather than holding a connection forever
            connect_args={"connect_timeout": 10, "options": "-c statement_timeout=60000"},
        )

    if settings.database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _configure_sqlite(dbapi_connection: object, _record: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            # WAL (2026-10-07): readers never wait for a writer, nor a writer
            # for readers. With the default rollback journal, a request that
            # read and then awaited the network (a full-text or record
            # lookup) made every other request queue behind it. NORMAL sync
            # is WAL's recommended durability/speed balance.
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
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
    if settings.auto_create_schema:
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
