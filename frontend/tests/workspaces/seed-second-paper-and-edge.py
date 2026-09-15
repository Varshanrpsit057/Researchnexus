"""Playwright test helper (Slice 3): create a second real paper plus a
trail edge from the seed to it, directly via the repository layer -- the
same reasoning as seed-real-profile.py applies (no working BYOK key or
outbound network access exists in this environment to produce these for
real through discovery). Everything that follows (viewing the trail,
accepting the edge) still runs against the real backend.

Mirrors the real production path: an edge is saved against a `run_id`
first, then stamped onto a workspace via `attach_run_edges_to_workspace`
(the same function `create_workspace`/`add_papers` call for a real
discovery run) -- GET .../trail filters on the edge's own `workspace_id`
column, so skipping this step silently produces an edge the workspace
can never see, found the first time this script ran without it.

Usage: python seed-second-paper-and-edge.py <seed_paper_id> <target_paper_id> <workspace_id>
"""

import sys

sys.path.insert(0, r"H:\Researchnexus\backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository as repo
from app.db.models import PaperORM, WorkspaceORM
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge

seed_paper_id = sys.argv[1]
target_paper_id = sys.argv[2]
workspace_id = sys.argv[3]

engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
session = sessionmaker(bind=engine)()

if session.get(PaperORM, target_paper_id) is None:
    session.add(
        PaperORM(
            id=target_paper_id,
            title="A Playwright Fixture Related Paper",
            title_hash=f"pw-fixture-{target_paper_id}",
            authors=["T. Fixture"],
            year=2024,
            venue=None,
            doi=None,
            arxiv_id=None,
            has_full_text=False,
            parse_confidence=None,
            page_count=None,
            sections=[],
            tables=[],
            references=[],
            warnings=[],
        )
    )
    session.commit()

# Unique per invocation, not just per seed paper: the seed paper is a
# fixture PDF that always dedupes to the same id across test runs, and
# attach_run_edges_to_workspace stamps *every* row sharing this run_id --
# a run_id derived only from seed_paper_id would re-attach edges left
# behind by earlier runs/debugging sessions onto today's fresh workspace.
run_id = f"run_pw_{seed_paper_id}_{target_paper_id}"
edge = TrailEdge(
    edge_id=f"edge_pw_{seed_paper_id}_{target_paper_id}",
    run_id=run_id,
    source_paper_id=seed_paper_id,
    target_paper_id=target_paper_id,
    relationship_type=RelationshipType.SIMILAR,
    detection_method=DetectionMethod.RULE,
    rule_fired="playwright_fixture_rule",
    evidence=[
        Evidence(
            span={"paper_id": target_paper_id, "quote": "a fixture evidence sentence for testing"},
            role="target_claim",
        )
    ],
    supporting_references=["Fixture Reference 2024"],
    confidence="medium",
    confidence_basis={"fixture": True},
)
repo.save_trail_edges(session, run_id, [edge])
session.commit()

workspace_row = session.get(WorkspaceORM, workspace_id)
attached = repo.attach_run_edges_to_workspace(session, run_id=run_id, workspace_id=workspace_id, owner_id=workspace_row.owner_id)
print(f"seeded target paper {target_paper_id}, edge {edge.edge_id}, attached {attached} edge(s) to {workspace_id}")
