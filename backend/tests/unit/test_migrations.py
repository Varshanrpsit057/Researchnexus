"""Alembic migrations actually run (Roadmap: 'reviewed by hand, never
trusted blind'; Data Model §15). Tests elsewhere use Base.metadata.create_all
for speed -- this is the one place the migration path itself is exercised."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

_BACKEND_DIR = Path(__file__).resolve().parents[2]


def test_alembic_upgrade_head_creates_expected_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic_smoke.db"
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")

    conn = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()

    assert {
        "papers", "paper_chunks", "jobs", "users", "api_keys", "research_profiles",
        "search_runs", "search_candidates", "ranked_papers", "paper_relationships",
        "alembic_version",
    } <= tables


def test_alembic_downgrade_removes_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic_smoke_down.db"
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    conn = sqlite3.connect(db_path)
    try:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()

    assert "papers" not in tables
    assert "paper_chunks" not in tables
    assert "jobs" not in tables
    assert "users" not in tables
    assert "api_keys" not in tables
    assert "research_profiles" not in tables
    assert "search_runs" not in tables
    assert "search_candidates" not in tables
    assert "ranked_papers" not in tables
    assert "paper_relationships" not in tables
