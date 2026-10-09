from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

# The production relevance model (fastembed) downloads and loads a real
# model; tests stay offline and deterministic with no embedder unless a test
# injects one explicitly. Env vars outrank .env, and Settings(_env_file=None)
# still reads them.
os.environ.setdefault("RESEARCHNEXUS_DISCOVERY_EMBEDDER", "none")
# chat and comparison search with the deterministic stand-ins in tests
os.environ.setdefault("RESEARCHNEXUS_RAG_EMBEDDER", "fake")
os.environ.setdefault("RESEARCHNEXUS_RAG_RERANKER", "fake")
# Adding papers to a workspace looks for their full text in the background;
# tests stay offline, and the tests of that switch it back on themselves.
os.environ.setdefault("RESEARCHNEXUS_FULLTEXT_AUTO", "false")
os.environ.setdefault("RESEARCHNEXUS_METADATA_LOOKUP", "false")  # no network on upload
# the test environment: emails kept in memory, plain-HTTP cookies, tables made at start
os.environ.setdefault("RESEARCHNEXUS_ENVIRONMENT", "test")
os.environ.setdefault("RESEARCHNEXUS_SECRET_KEY", "test-only-secret-key-for-otp-and-csrf-hmacs")

from tests.fixtures.make_fixtures import (
    make_corrupt_pdf,
    make_duplicate_text_pdf,
    make_encrypted_pdf,
    make_ieee_style_pdf,
    make_multi_page_pdf,
    make_normal_paper_pdf,
    make_not_a_pdf_bytes,
    make_scanned_pdf,
    make_two_column_paper_pdf,
)

_PG_URL = os.environ.get("RESEARCHNEXUS_TEST_POSTGRES_URL")
_ON_POSTGRES = os.environ.get("RESEARCHNEXUS_TEST_ON_POSTGRES") == "1" and bool(_PG_URL)
_PG_TEMPLATE = "rn_test_template"


@pytest.fixture(scope="session")
def _postgres_template() -> Iterator[None]:
    """A database migrated once, cloned for each test (CREATE DATABASE ...
    TEMPLATE is fast)."""
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config

    admin = sa.create_engine(str(_PG_URL), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{_PG_TEMPLATE}" WITH (FORCE)'))
        conn.execute(sa.text(f'CREATE DATABASE "{_PG_TEMPLATE}"'))
    backend = Path(__file__).resolve().parents[1]
    cfg = Config(str(backend / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend / "migrations"))
    cfg.set_main_option("sqlalchemy.url", sa.engine.make_url(str(_PG_URL)).set(database=_PG_TEMPLATE).render_as_string(hide_password=False))
    command.upgrade(cfg, "head")
    yield
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{_PG_TEMPLATE}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(autouse=True)
def _postgres_instead_of_sqlite(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """RESEARCHNEXUS_TEST_ON_POSTGRES=1 (with RESEARCHNEXUS_TEST_POSTGRES_URL):
    every app a test builds on a SQLite file runs on its own PostgreSQL
    database instead -- the same one for the same file, so a "restarted"
    app sees the data -- migrated with alembic, as a deployment's would be."""
    if not _ON_POSTGRES:
        yield
        return
    import uuid

    import sqlalchemy as sa

    import app.db.session as db_session
    from app.config import Settings

    request.getfixturevalue("_postgres_template")
    real = db_session.make_engine
    databases: dict[str, str] = {}
    admin = sa.create_engine(str(_PG_URL), isolation_level="AUTOCOMMIT")

    def on_postgres(settings: Settings) -> sa.Engine:
        if settings.database_url.startswith("sqlite"):
            name = databases.get(settings.database_url)
            if name is None:
                name = databases[settings.database_url] = f"rn_t_{uuid.uuid4().hex[:12]}"
                with admin.connect() as conn:
                    conn.execute(sa.text(f'CREATE DATABASE "{name}" TEMPLATE "{_PG_TEMPLATE}"'))
            url = sa.engine.make_url(str(_PG_URL)).set(database=name).render_as_string(hide_password=False)
            settings = settings.model_copy(update={"database_url": url})
        return real(settings)

    monkeypatch.setattr(db_session, "make_engine", on_postgres)
    yield
    if db_session._engine is not None:
        db_session._engine.dispose()
    with admin.connect() as conn:
        for name in databases.values():
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture(autouse=True)
def _cheap_password_hashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argon2 at production cost takes ~80 ms a hash; tests hash many."""
    from argon2 import PasswordHasher

    monkeypatch.setattr("app.security.passwords._hasher", PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))


@pytest.fixture(autouse=True)
def _empty_outbox() -> None:
    from app.services import mail

    mail.outbox.clear()


@pytest.fixture(autouse=True)
def _no_provider_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider adapter backs off for real seconds between retries; tests
    of a failing provider don't wait them out (tests of the backoff itself
    inject their own `sleep`)."""

    async def instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("app.llm.providers.openai_compat.backoff_sleep", instant)


@pytest.fixture(scope="session")
def normal_paper_pdf_bytes() -> bytes:
    return make_normal_paper_pdf()


@pytest.fixture(scope="session")
def two_column_paper_pdf_bytes() -> bytes:
    return make_two_column_paper_pdf()


@pytest.fixture(scope="session")
def scanned_pdf_bytes() -> bytes:
    return make_scanned_pdf()


@pytest.fixture(scope="session")
def duplicate_text_pdf_bytes() -> bytes:
    return make_duplicate_text_pdf()


@pytest.fixture(scope="session")
def ieee_style_pdf_bytes() -> bytes:
    return make_ieee_style_pdf()


@pytest.fixture(scope="session")
def encrypted_pdf_bytes() -> bytes:
    return make_encrypted_pdf()


@pytest.fixture(scope="session")
def corrupt_pdf_bytes() -> bytes:
    return make_corrupt_pdf()


@pytest.fixture(scope="session")
def not_a_pdf_bytes() -> bytes:
    return make_not_a_pdf_bytes()


@pytest.fixture()
def multi_page_pdf_factory() -> Callable[[int], bytes]:
    return make_multi_page_pdf
