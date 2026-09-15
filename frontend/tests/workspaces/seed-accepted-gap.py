"""Playwright test helper (Slice 7): persist one real, already-accepted
ResearchGap directly via the repository layer -- the same reasoning as
seed-real-profile.py applies (gap generation is LLM-gated and no working
BYOK key exists in this environment). Directions may only be generated
from a gap that is both `user_state="accepted"` and `self_support_passed`
(see services/directions/pipeline.py's build_directions), so this seeds
both flags set correctly rather than routing through set_gap_user_state
afterward -- repo.save_gaps already accepts either state on first insert.

Usage: python seed-accepted-gap.py <gap_id> <seed_paper_id> <second_paper_id> <workspace_id>
"""

import sys

sys.path.insert(0, r"H:\Researchnexus\backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository as repo
from app.db.models import WorkspaceORM
from app.domain.gap import Confidence, GapEvidence, GapType, ResearchGap
from app.domain.profile import SourceSpan

gap_id = sys.argv[1]
seed_paper_id = sys.argv[2]
second_paper_id = sys.argv[3]
workspace_id = sys.argv[4]

engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
session = sessionmaker(bind=engine)()

gap = ResearchGap(
    gap_id=gap_id,
    workspace_id=workspace_id,
    statement="No compared method reports results under low-resource training data.",
    gap_type=GapType.EVALUATION_GAP,
    supporting_papers=[seed_paper_id, second_paper_id],
    supporting_evidence=[
        GapEvidence(
            paper_id=seed_paper_id,
            span=SourceSpan(paper_id=seed_paper_id, section="Limitations", page=8, quote="we did not evaluate under low-resource conditions"),
        )
    ],
    why_unaddressed="Both papers evaluate only on full-scale training sets.",
    evidence_coverage=0.6,
    confidence=Confidence.MEDIUM,
    confidence_basis={"agreement": "2 of 2 papers support this reading"},
    self_support_passed=True,
    user_state="accepted",
)

workspace_row = session.get(WorkspaceORM, workspace_id)
repo.save_gaps(session, workspace_id, [gap], owner_id=workspace_row.owner_id)
print(f"seeded accepted gap {gap_id} in {workspace_id}")
