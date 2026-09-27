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
        "research_directions", "stage_runs",
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
    assert "stage_runs" not in tables


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


def test_0014_lets_each_workspace_hold_its_own_copy_of_a_runs_trail_edge(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic_trail_copies.db"
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "0013")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO papers (id, title, title_hash, has_full_text, source, created_at) VALUES "
                     "('pap_s', 'S', 'hs', 1, 'upload', '2026-01-01'), ('pap_t', 'T', 'ht', 0, 'discovery', '2026-01-01')")
        conn.execute("INSERT INTO search_runs (id, seed_paper_id, started_at) VALUES ('run_1', 'pap_s', '2026-01-01')")
        edge = ("run_1", "pap_s", "pap_t", "SIMILAR", "rule", "medium", "2026-01-01")
        conn.execute(
            "INSERT INTO paper_relationships (id, workspace_id, run_id, source_paper_id, target_paper_id, "
            "relationship_type, detection_method, confidence, created_at) VALUES ('edge_1', 'ws_1', ?, ?, ?, ?, ?, ?, ?)",
            edge,
        )
        conn.commit()
    finally:
        conn.close()

    command.upgrade(cfg, "head")
    conn = sqlite3.connect(db_path)
    try:
        # existing rows survive as the run's primaries
        assert conn.execute("SELECT id, workspace_id, copied_from FROM paper_relationships").fetchall() == [("edge_1", "ws_1", None)]
        insert_copy = (
            "INSERT INTO paper_relationships (id, workspace_id, copied_from, run_id, source_paper_id, target_paper_id, "
            "relationship_type, detection_method, confidence, created_at) VALUES (?, ?, 'edge_1', ?, ?, ?, ?, ?, ?, ?)"
        )
        conn.execute(insert_copy, ("edge_2", "ws_2", *edge))  # a second workspace's copy now fits
        conn.commit()
        dupes = 0
        for sql, params in [
            (insert_copy, ("edge_3", "ws_2", *edge)),  # a second copy for the same workspace
            (
                "INSERT INTO paper_relationships (id, run_id, source_paper_id, target_paper_id, relationship_type, "
                "detection_method, confidence, created_at) VALUES ('edge_4', ?, ?, ?, ?, ?, ?, ?)",
                edge,
            ),  # a second primary for the same connection
        ]:
            try:
                conn.execute(sql, params)
            except sqlite3.IntegrityError:
                dupes += 1
        assert dupes == 2
    finally:
        conn.close()

    command.downgrade(cfg, "0013")
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(paper_relationships)")}
        rows = conn.execute("SELECT id FROM paper_relationships").fetchall()
    finally:
        conn.close()
    assert "copied_from" not in cols
    assert rows == [("edge_1",)]  # the copies cannot fit the old key, so they go


def test_0015_keeps_an_answers_outcome_on_chat_messages(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic_chat_outcome.db"
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)")}
    finally:
        conn.close()
    assert {"suggestion", "unsupported_dropped", "warnings"} <= cols

    command.downgrade(cfg, "0014")
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(chat_messages)")}
    finally:
        conn.close()
    assert not {"suggestion", "unsupported_dropped", "warnings"} & cols


def test_0016_stores_a_users_default_provider(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic_default_provider.db"
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "0015")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO users (id, email, auth_provider, auth_subject, created_at) VALUES ('u1', 'a@b.c', 'local', 'a@b.c', '2026-01-01')")
        conn.commit()
    finally:
        conn.close()

    command.upgrade(cfg, "head")
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        existing = conn.execute("SELECT default_provider FROM users WHERE id = 'u1'").fetchone()
    finally:
        conn.close()
    assert "default_provider" in cols
    assert existing == (None,)  # existing users keep "first working key" until they choose

    command.downgrade(cfg, "0015")
    conn = sqlite3.connect(db_path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
    finally:
        conn.close()
    assert "default_provider" not in cols


def test_0017_records_each_provider_call_and_its_usage(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic_llm_calls.db"
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

    command.upgrade(cfg, "head")
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO users (id, email, auth_provider, auth_subject, created_at) VALUES ('u1', 'a@b.c', 'local', 'a@b.c', '2026-01-01')")
        conn.execute(
            "INSERT INTO llm_calls (id, owner_id, workspace_id, feature, provider, model, created_at) "
            "VALUES ('llm_1', 'u1', 'ws_gone', 'chat', 'deepseek', 'deepseek-flash', '2026-09-27')"
        )
        conn.commit()
        row = conn.execute(
            "SELECT prompt_tokens, completion_tokens, cached_prompt_tokens, reasoning_tokens, ok, error_kind FROM llm_calls"
        ).fetchone()
        indexes = {r[1] for r in conn.execute("PRAGMA index_list(llm_calls)")}
    finally:
        conn.close()
    # counts default to zero; a workspace id needs no workspace row (usage outlives a deleted workspace)
    assert row == (0, 0, 0, 0, 1, None)
    assert {"ix_llm_calls_owner_created", "ix_llm_calls_workspace"} <= indexes

    command.downgrade(cfg, "0016")
    conn = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "llm_calls" not in tables
