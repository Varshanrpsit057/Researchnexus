"""Migrations 0021 (sign-in) and 0022 (job runners, TEXT columns); the
migrated schema matches the models; and, when a PostgreSQL server is given
(RESEARCHNEXUS_TEST_POSTGRES_URL, as CI does), the whole chain runs there
too -- up, down and up again."""

from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.db import models  # noqa: F401 - registers the tables
from app.db.base import Base

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_POSTGRES = os.environ.get("RESEARCHNEXUS_TEST_POSTGRES_URL")


def _config(url: str) -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def _schema(engine: sa.Engine) -> dict[str, set[str]]:
    inspector = sa.inspect(engine)
    return {t: {c["name"] for c in inspector.get_columns(t)} for t in inspector.get_table_names() if t != "alembic_version"}


def test_0021_adds_sign_in_without_touching_existing_accounts(tmp_path: Path) -> None:
    db_path = tmp_path / "auth.db"
    cfg = _config(f"sqlite:///{db_path}")
    command.upgrade(cfg, "0020")
    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO users (id, email, auth_provider, auth_subject, created_at) VALUES ('usr_old', 'Old@Example.org', 'local', 'Old@Example.org', '2026-01-01')")
    conn.commit()
    conn.close()

    command.upgrade(cfg, "head")
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT id, email, name, password_hash, email_verified_at FROM users").fetchall() == [
            ("usr_old", "Old@Example.org", None, None, None)
        ]
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"auth_sessions", "auth_challenges", "rate_limits", "job_runners"} <= tables
        assert "runner_id" in {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        # the case-insensitive email lookup has its index
        plan = " ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN SELECT id FROM users WHERE lower(email) = 'old@example.org'"))
        assert "ix_users_email_lower" in plan
    finally:
        conn.close()

    command.downgrade(cfg, "0020")
    conn = sqlite3.connect(db_path)
    try:
        assert {r[1] for r in conn.execute("PRAGMA table_info(users)")} == {"id", "email", "auth_provider", "auth_subject", "created_at", "default_provider"}
        assert conn.execute("SELECT id FROM users").fetchall() == [("usr_old",)]
    finally:
        conn.close()


def test_0021_and_0022_complete_on_a_database_that_already_has_their_tables(tmp_path: Path) -> None:
    """A development server makes missing tables at start; migrating such a
    database afterwards must not fail on them."""
    db_path = tmp_path / "made.db"
    cfg = _config(f"sqlite:///{db_path}")
    command.upgrade(cfg, "0020")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    for name in ("auth_sessions", "auth_challenges", "rate_limits", "job_runners"):
        Base.metadata.tables[name].create(engine)
    engine.dispose()
    command.upgrade(cfg, "head")
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == ("0023",)
    finally:
        conn.close()


def test_the_migrated_schema_has_every_table_and_column_the_models_have(tmp_path: Path) -> None:
    migrated = tmp_path / "migrated.db"
    command.upgrade(_config(f"sqlite:///{migrated}"), "head")
    created = sa.create_engine(f"sqlite:///{tmp_path / 'created.db'}")
    Base.metadata.create_all(created)
    from_models = _schema(created)
    from_migrations = _schema(sa.create_engine(f"sqlite:///{migrated}"))
    assert from_migrations == from_models


@pytest.mark.skipif(not _POSTGRES, reason="set RESEARCHNEXUS_TEST_POSTGRES_URL to run the migrations on PostgreSQL")
def test_every_migration_runs_on_postgresql_and_matches_the_models() -> None:
    assert _POSTGRES is not None
    admin = sa.create_engine(_POSTGRES, isolation_level="AUTOCOMMIT")
    name = f"rn_migrate_{uuid.uuid4().hex[:10]}"
    with admin.connect() as conn:
        conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = sa.engine.make_url(_POSTGRES).set(database=name)
    try:
        cfg = _config(url.render_as_string(hide_password=False))
        command.upgrade(cfg, "head")
        engine = sa.create_engine(url)
        migrated = _schema(engine)
        with engine.connect() as conn:
            # a long, real-world value fits once the free-text columns are TEXT
            conn.execute(sa.text("INSERT INTO papers (id, title, title_hash, has_full_text, source, created_at, venue, url) "
                                 "VALUES ('pap_1', 't', 'h', false, 'upload', now(), :venue, :url)"), {"venue": "V" * 600, "url": "https://x.org/" + "a" * 3000})
            conn.commit()
        # going back can't fit that value: PostgreSQL refuses rather than cut it
        with pytest.raises(sa.exc.DataError):
            command.downgrade(cfg, "0020")
        with engine.connect() as conn:
            conn.execute(sa.text("DELETE FROM papers"))
            conn.commit()
        engine.dispose()
        command.downgrade(cfg, "0020")
        command.upgrade(cfg, "head")
        created_name = f"{name}_models"
        with admin.connect() as conn:
            conn.execute(sa.text(f'CREATE DATABASE "{created_name}"'))
        created = sa.create_engine(url.set(database=created_name))
        Base.metadata.create_all(created)
        assert migrated == _schema(created)
        created.dispose()
    finally:
        with admin.connect() as conn:
            for db in (name, f"{name}_models"):
                conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)'))
        admin.dispose()


@pytest.mark.skipif(not _POSTGRES, reason="set RESEARCHNEXUS_TEST_POSTGRES_URL to copy into PostgreSQL")
def test_a_sqlite_database_is_copied_into_an_empty_postgresql_one_and_nothing_is_merged(tmp_path: Path) -> None:
    from app.maintenance.sqlite_to_postgres import CopyRefused, copy_database

    assert _POSTGRES is not None
    sqlite_file = tmp_path / "local.db"
    command.upgrade(_config(f"sqlite:///{sqlite_file}"), "head")
    conn = sqlite3.connect(sqlite_file)
    conn.executescript(
        """
        INSERT INTO users (id, email, auth_provider, auth_subject, created_at) VALUES ('usr_1', 'a@b.org', 'local', 'a@b.org', '2026-01-01 00:00:00');
        INSERT INTO papers (id, title, title_hash, has_full_text, source, created_at, authors, sections, tables, "references", warnings)
          VALUES ('pap_1', 'A paper', 'h1', 1, 'upload', '2026-01-01 00:00:00', '["Ada"]', '[]', '[]', '[]', '[]');
        INSERT INTO paper_chunks (id, paper_id, kind, text, section_order, char_start, char_end, token_count) VALUES ('chk_1', 'pap_1', 'body', 'kept', 0, 0, 4, 1);
        INSERT INTO paper_chunks (id, paper_id, kind, text, section_order, char_start, char_end, token_count) VALUES ('chk_gone', 'pap_deleted', 'body', 'orphan', 0, 0, 6, 1);
        """
    )
    conn.commit()
    conn.close()

    admin = sa.create_engine(_POSTGRES, isolation_level="AUTOCOMMIT")
    name = f"rn_copy_{uuid.uuid4().hex[:10]}"
    with admin.connect() as c:
        c.execute(sa.text(f'CREATE DATABASE "{name}"'))
    url = sa.engine.make_url(_POSTGRES).set(database=name).render_as_string(hide_password=False)
    try:
        command.upgrade(_config(url), "head")
        with pytest.raises(CopyRefused, match="paper_chunks 1"):
            copy_database(sqlite_file, url, out=lambda _line: None)  # an orphan: refused, nothing kept
        copied = copy_database(sqlite_file, url, skip_orphans=True, out=lambda _line: None)
        assert copied["users"] == 1 and copied["papers"] == 1 and copied["paper_chunks"] == 1
        engine = sa.create_engine(url)
        with engine.connect() as c:
            assert c.execute(sa.text("SELECT authors FROM papers")).scalar_one() == ["Ada"]
        engine.dispose()
        with pytest.raises(CopyRefused, match="already has rows"):
            copy_database(sqlite_file, url, skip_orphans=True, out=lambda _line: None)
        assert any(p.name.startswith("local.db.bak-pre-postgres-") for p in tmp_path.iterdir())
    finally:
        with admin.connect() as c:
            c.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()
