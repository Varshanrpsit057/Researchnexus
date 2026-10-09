"""Copy a ResearchNexus SQLite database into an empty PostgreSQL database
(moving a local or single-machine install onto the deployed setup).

    python -m app.maintenance.sqlite_to_postgres SQLITE_FILE POSTGRES_URL [--dry-run]

What it does, in order -- and what it refuses to do:

1. Backs the SQLite file up first (SQLite's own backup API: a consistent
   copy, writes still in the WAL file included), next to it.
2. Checks both schemas are at the same migration revision (run
   `alembic upgrade head` on each first). Refuses otherwise.
3. Refuses a PostgreSQL database that already holds any rows: it never
   merges into, overwrites or deletes existing data.
4. Copies every table in foreign-key order, in one transaction, through the
   same table definitions the app uses (so dates, JSON and binary values
   convert exactly as the app writes them). Every id is a string, so there
   are no sequences to reset.
5. Finds orphans -- rows pointing at a row that no longer exists (SQLite
   only enforces foreign keys when asked, so test clean-ups and old scripts
   left some behind; PostgreSQL refuses them). It stops and reports them per
   table, unless `--skip-orphans` says to leave them out of the copy (they
   stay in the SQLite file and its backup).
6. Verifies the row count of every table matches what was meant to be
   copied, and rolls the whole copy back if any doesn't.

The SQLite file is only read. Uploaded PDFs are files, not rows: copy the
data directory (`RESEARCHNEXUS_DATA_DIR`, e.g. `backend/data/papers`) to
the new storage (EFS) separately -- stored paths are relative to it.
`--dry-run` does steps 1-3 and reports what would be copied.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import sqlalchemy as sa

from app.db import models  # noqa: F401 - registers every table
from app.db.base import Base

# copied in batches so a large table never sits in memory at once
_BATCH = 500
_SKIP = {"alembic_version", "rate_limits", "job_runners"}  # bookkeeping, not data


class CopyRefused(RuntimeError):
    pass


def backup_sqlite(path: Path) -> Path:
    target = path.with_name(f"{path.name}.bak-pre-postgres-{datetime.now():%Y%m%d-%H%M%S}")
    src, dst = sqlite3.connect(path), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def _revision(conn: sa.Connection) -> str | None:
    try:
        return conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except sa.exc.DBAPIError:
        conn.rollback()
        return None


def copy_database(
    sqlite_path: Path, postgres_url: str, *, dry_run: bool = False, skip_orphans: bool = False, out=print  # noqa: ANN001
) -> dict[str, int]:
    if not sqlite_path.is_file():
        raise CopyRefused(f"no SQLite database at {sqlite_path}")
    backup = backup_sqlite(sqlite_path)
    out(f"backed up {sqlite_path.name} to {backup}")

    source = sa.create_engine(f"sqlite:///{sqlite_path}")
    target = sa.create_engine(postgres_url)
    tables = [t for t in Base.metadata.sorted_tables if t.name not in _SKIP]
    counts: dict[str, int] = {}
    try:
        with source.connect() as src, target.connect() as dst:
            src_rev, dst_rev = _revision(src), _revision(dst)
            if src_rev is None or src_rev != dst_rev:
                raise CopyRefused(
                    f"migration revisions differ (SQLite {src_rev}, PostgreSQL {dst_rev}): "
                    "run `alembic upgrade head` on both first"
                )
            present = set(sa.inspect(dst).get_table_names())
            for table in tables:
                if table.name in present and dst.execute(sa.select(sa.func.count()).select_from(table)).scalar_one():
                    raise CopyRefused(f"PostgreSQL already has rows in {table.name}: refusing to merge or overwrite")
            src_present = set(sa.inspect(src).get_table_names())
            for table in tables:
                counts[table.name] = src.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() if table.name in src_present else 0
            if dry_run:
                for name, n in counts.items():
                    out(f"would copy {n:>7} rows  {name}")
                return counts

            # the values each foreign key points at, from the rows actually copied
            referenced = {(fk.column.table.name, fk.column.name) for t in tables for fk in t.foreign_keys}
            kept: dict[tuple[str, str], set[object]] = {key: set() for key in referenced}
            orphans: dict[str, int] = {}
            copied: dict[str, int] = {}
            dst.rollback()  # end the read-only checks' transaction; the copy is one transaction of its own
            with dst.begin():
                for table in tables:
                    links = [(fk.parent.name, (fk.column.table.name, fk.column.name)) for fk in table.foreign_keys]
                    copied[table.name] = 0
                    if not counts[table.name]:
                        continue
                    result = src.execution_options(stream_results=True).execute(sa.select(table))
                    while rows := result.fetchmany(_BATCH):
                        batch = []
                        for row in rows:
                            values = dict(row._mapping)
                            if any(values[col] is not None and values[col] not in kept[target] for col, target in links):
                                orphans[table.name] = orphans.get(table.name, 0) + 1
                                continue
                            batch.append(values)
                            for name, col in referenced:
                                if name == table.name:
                                    kept[(name, col)].add(values[col])
                        if batch:
                            dst.execute(table.insert(), batch)
                            copied[table.name] += len(batch)
                    out(f"copied {copied[table.name]:>7} rows  {table.name}" + (f"  ({orphans[table.name]} orphans left out)" if table.name in orphans else ""))
                if orphans and not skip_orphans:
                    raise CopyRefused(
                        "rows pointing at rows that no longer exist (nothing was kept): "
                        + ", ".join(f"{name} {n}" for name, n in orphans.items())
                        + ". Re-run with --skip-orphans to copy everything else."
                    )
                mismatched = {
                    t.name: (copied[t.name], n)
                    for t in tables
                    if (n := dst.execute(sa.select(sa.func.count()).select_from(t)).scalar_one()) != copied[t.name]
                }
                if mismatched:
                    raise CopyRefused(f"row counts differ after copying, nothing kept: {mismatched}")
            total = sum(copied.values())
            out(f"verified: {total} rows in {sum(1 for n in copied.values() if n)} tables match; {sum(orphans.values())} orphans left out")
            return copied
    finally:
        source.dispose()
        target.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("sqlite_file", type=Path)
    parser.add_argument("postgres_url", help="postgresql+psycopg://user:password@host:5432/db (quote it in the shell)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-orphans", action="store_true", help="leave out rows pointing at rows that no longer exist")
    args = parser.parse_args(argv)
    try:
        copy_database(args.sqlite_file, args.postgres_url, dry_run=args.dry_run, skip_orphans=args.skip_orphans)
    except CopyRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 1
    except sa.exc.DBAPIError as e:
        # the database's own reason, without the rows it was given
        print(f"failed, nothing was kept: {type(e.orig).__name__}: {str(e.orig).splitlines()[0]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
