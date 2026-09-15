"""Playwright test helper (Slice 3): insert a minimal, valid ResearchProfile
directly via the repository layer for a paper the test has already uploaded
for real through the running dev backend.

This exists because workspace creation's real backend check
(`SeedNotAnalyzed`) requires an actually-persisted profile, and `analyze`
is LLM-gated -- no working BYOK provider key exists in this environment.
Everything downstream of this one seeding step (create workspace, add
papers, trail accept/reject) then runs against the real backend with no
mocking at all, which is the point: this script exists to unblock real
integration testing, not to replace it.

Usage: python seed-real-profile.py <paper_id> <title>
"""

import sys

sys.path.insert(0, r"H:\Researchnexus\backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository as repo
from app.domain.profile import Confidence, ProfileField, ProfileList, ResearchProfile

paper_id = sys.argv[1]
title = sys.argv[2]

engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
session = sessionmaker(bind=engine)()

profile = ResearchProfile(
    profile_id=f"prof_pw_{paper_id}",
    paper_id=paper_id,
    title=title,
    abstract=f"A Playwright test fixture profile for {title}.",
    domain=ProfileField(value="Test domain", status="verified"),
    research_problem=ProfileField(value="A test research problem."),
    methods=ProfileList(items=[ProfileField(value="A test method.")]),
    keywords=["playwright", "fixture"],
    extraction_confidence=Confidence.HIGH,
    extraction_model="playwright-seed-script",
)
repo.upsert_profile(session, profile)
session.commit()
print(f"seeded profile for {paper_id}")
