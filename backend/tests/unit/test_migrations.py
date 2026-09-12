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
        "workspaces", "workspace_papers",
        "chat_sessions", "chat_messages", "citations", "claims", "comparisons", "research_gaps",
        "research_directions",
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
    assert "workspaces" not in tables
    assert "workspace_papers" not in tables
    assert "chat_sessions" not in tables
    assert "chat_messages" not in tables
    assert "citations" not in tables
    assert "claims" not in tables
    assert "comparisons" not in tables
    assert "research_gaps" not in tables
    assert "research_directions" not in tables


def test_alembic_upgrade_adds_workspaces_graph_json_and_downgrade_removes_it(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic_graph_smoke.db"
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(workspaces)")}
    finally:
        conn.close()
    assert "graph_json" in cols

    command.downgrade(cfg, "0011")
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(workspaces)")}
    finally:
        conn.close()
    assert "graph_json" not in cols
