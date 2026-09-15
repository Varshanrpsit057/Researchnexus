"""Playwright test helper (Slice 3): delete the profile seed-real-profile.py
inserted for a paper. The dev database this suite runs against is a
persistent file shared across every spec and every run, not a fresh
per-test database, so anything a test seeds as *persisted* backend state
(as opposed to network-layer mocks, which vanish with the test) leaks into
every other spec that reuses the same fixture PDF -- discovered live: this
test's own real-profile seeding, run standalone a few times while writing
it, left analyze-flow.spec.ts and discover-flow.spec.ts finding an
already-analyzed paper where they expect a fresh one, failing both.

Usage: python cleanup-seeded-profile.py <paper_id>
"""

import sys

sys.path.insert(0, r"H:\Researchnexus\backend")

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker

from app.db.models import ResearchProfileORM

paper_id = sys.argv[1]

engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
session = sessionmaker(bind=engine)()
result = session.execute(delete(ResearchProfileORM).where(ResearchProfileORM.paper_id == paper_id))
session.commit()
print(f"removed {result.rowcount} profile row(s) for {paper_id}")
