"""Re-read every uploaded paper's stored PDF with the current reader and
complete its record from its sources (remediation, 2026-10-02).

Earlier reads glued the words of tightly set PDFs together, read IEEE first
pages across both columns and missed inline abstracts; this brings every
stored upload up to the current reader. The database is copied first.

usage (from backend/):  python -m app.maintenance.reread_uploads [--no-metadata | --records-only]
"""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db.models import PaperORM
from app.db.session import configure, get_session_factory
from app.jobs.runner import complete_metadata
from app.services.ingest.reread import NoStoredPdf, reread_stored_pdf


def _backup(database_url: str, backend: Path) -> Path | None:
    if not database_url.startswith("sqlite:///"):
        return None
    db_file = (backend / database_url.removeprefix("sqlite:///")).resolve()
    if not db_file.is_file():
        return None
    backup = db_file.with_name(f"{db_file.name}.bak-pre-reread-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(db_file, backup)
    return backup


def _complete_records(db, settings) -> int:  # noqa: ANN001
    """Look up the record of every upload still missing one (each title once:
    copies of one PDF share its record)."""
    seen: set[str] = set()
    found = 0
    rows = db.execute(
        select(PaperORM.id, PaperORM.title).where(PaperORM.source == "upload", PaperORM.year.is_(None))
    ).all()
    for pid, title in rows:
        key = (title or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        meta = complete_metadata(db, pid, settings)
        found += meta.get("metadata") == "found"
        print(f"{pid} {title[:60]!r}: record {meta.get('metadata')} {meta.get('sources') or ''}")
    print(f"{found} of {len(seen)} records completed")
    return 0


def main(argv: list[str]) -> int:
    settings = get_settings()
    if "--records-only" in argv:
        configure(settings)
        db = get_session_factory()()
        try:
            return _complete_records(db, settings)
        finally:
            db.close()
    lookups = "--no-metadata" not in argv
    backup = _backup(settings.database_url, Path(__file__).resolve().parents[2])
    print(f"database backed up to {backup}" if backup else "database not backed up (not a SQLite file)")
    configure(settings)
    db = get_session_factory()()
    try:
        ids = [
            pid
            for pid, path in db.execute(select(PaperORM.id, PaperORM.pdf_path).where(PaperORM.source == "upload")).all()
            if path and Path(path).is_file()
        ]
        print(f"{len(ids)} uploaded papers have a stored PDF")
        abstracts = found = failed = 0
        for n, pid in enumerate(ids, 1):
            try:
                outcome = reread_stored_pdf(db, pid, settings)
            except NoStoredPdf:
                continue
            except Exception as e:  # noqa: BLE001 - one unreadable PDF must not stop the rest
                db.rollback()
                failed += 1
                print(f"[{n}/{len(ids)}] {pid}: could not be read again ({type(e).__name__})")
                continue
            abstracts += outcome.abstract_found
            meta = complete_metadata(db, pid, settings) if lookups else {}
            found += meta.get("metadata") == "found"
            print(f"[{n}/{len(ids)}] {pid}: {outcome.chunks} passages, abstract {'yes' if outcome.abstract_found else 'no'}, record {meta.get('metadata', 'skipped')}")
        print(f"done: {len(ids) - failed} read again ({abstracts} with an abstract), {found} records completed, {failed} failed")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
