"""Name the publisher of every stored paper that has a DOI but no publisher
yet (remediation, 2026-10-02): papers saved before publishers were captured.
A DOI's prefix is registered to one publisher, so this reads, not guesses.

usage (from backend/):  python -m app.maintenance.backfill_publishers
"""

from __future__ import annotations

import sys
from collections import Counter

from sqlalchemy import select

from app.config import get_settings
from app.db.models import PaperORM
from app.db.session import configure, get_session_factory
from app.services.metadata.publishers import from_doi, normalize


def main() -> int:
    configure(get_settings())
    db = get_session_factory()()
    try:
        rows = db.execute(select(PaperORM).where(PaperORM.publisher.is_(None), PaperORM.doi.is_not(None))).scalars().all()
        named: Counter[str] = Counter()
        for paper in rows:
            publisher = from_doi(paper.doi)
            if publisher:
                paper.publisher = publisher
                named[publisher] += 1
        db.commit()
        print(f"{sum(named.values())} of {len(rows)} papers with a DOI now name their publisher")
        # names stored before they were all normalised ("Association for Computational Linguistics")
        renamed = 0
        for paper in db.execute(select(PaperORM).where(PaperORM.publisher.is_not(None))).scalars():
            canonical = normalize(paper.publisher)
            if canonical and canonical != paper.publisher:
                paper.publisher = canonical
                renamed += 1
        db.commit()
        print(f"{renamed} publisher names normalised")
        for name, n in named.most_common(12):
            print(f"  {name}: {n}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
