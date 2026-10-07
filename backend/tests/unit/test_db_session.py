"""SQLite under concurrent requests (2026-10-07): with the default rollback
journal, one request holding the database while it waits on the network
made every other request queue behind it (an upload took 5.5 s, and the
library never loaded). In WAL mode a reader never waits for a writer, and a
writer for readers."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from sqlalchemy import Engine, text

from app.config import Settings
from app.db.session import make_engine


def _engine(tmp_path: Path) -> Engine:
    settings = Settings(_env_file=None, data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'db.sqlite'}", jwt_secret="x")  # type: ignore[call-arg]
    return make_engine(settings)


def test_the_database_runs_in_wal_mode_with_foreign_keys(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 15000


def test_a_write_is_not_held_up_by_a_long_read(tmp_path: Path) -> None:
    # what stalled the app: a request reads, then awaits the network with its
    # transaction still open; meanwhile another request writes
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE t (x INTEGER)"))
        conn.execute(text("INSERT INTO t VALUES (1)"))

    reader = engine.connect()
    reader.execute(text("BEGIN"))
    assert reader.execute(text("SELECT count(*) FROM t")).scalar() == 1  # a read transaction left open

    done: list[float] = []

    def write() -> None:
        started = time.monotonic()
        with engine.begin() as conn:
            conn.execute(text("PRAGMA busy_timeout = 1000"))
            conn.execute(text("INSERT INTO t VALUES (2)"))
        done.append(time.monotonic() - started)

    writer = threading.Thread(target=write)
    writer.start()
    writer.join(timeout=5)
    try:
        assert done and done[0] < 0.5, "the write waited for the read"
        # and a new reader sees the write at once
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM t")).scalar() == 2
    finally:
        reader.execute(text("ROLLBACK"))
        reader.close()
