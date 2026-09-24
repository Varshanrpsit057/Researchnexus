"""Playwright test helper (Phase 6): persist one real, completed discovery
run for a seed paper -- two related papers, their ranking, and a pending
trail edge to each -- through the same repository calls the real
discover/rank/trail pipelines write through (mirrors the backend's own
test_import_run_attaches_trail_and_accepts_imported_edges).

Discovery itself can't run here (no outbound access to arXiv, OpenAlex,
Semantic Scholar, or Crossref), so the spec mocks only the job start/poll
and points it at this run. Everything after that -- the /related listing,
creating the workspace with the run imported, adding papers from it, and
the trail edges being accepted -- runs against the real backend.

Usage: python seed-discovery-run.py <seed_paper_id> <run_id> <first_paper_id> <second_paper_id>
"""

import sys

sys.path.insert(0, r"H:\Researchnexus\backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository as repo
from app.db.models import PaperORM
from app.domain.candidate import CitationRelationship, DiscoveryStrategy, SearchRun
from app.domain.profile import Confidence, SourceSpan
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge

seed_paper_id, run_id, first_id, second_id = sys.argv[1:5]

engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
session = sessionmaker(bind=engine)()

RELATED = [
    # id, title, authors, year, venue, rank, band, score, relationship
    (first_id, "Phase 6 Fixture: A Dense Retrieval Baseline", ["A. Fixture", "B. Fixture"], 2021, "Fixture Proceedings", 1, Confidence.HIGH, 0.84, RelationshipType.SIMILAR),
    (second_id, "Phase 6 Fixture: A Late-Interaction Reranker", ["C. Fixture"], 2022, None, 2, Confidence.MEDIUM, 0.61, RelationshipType.METHOD_EXTENSION),
]

for pid, title, authors, year, venue, *_ in RELATED:
    if session.get(PaperORM, pid) is None:
        session.add(
            PaperORM(
                id=pid,
                title=title,
                title_hash=f"pw-phase6-{pid}",
                authors=authors,
                year=year,
                venue=venue,
                has_full_text=False,
                source="discovery",
                sections=[],
                tables=[],
                references=[],
                warnings=[],
            )
        )
session.commit()

repo.create_search_run(
    session,
    SearchRun(
        run_id=run_id,
        seed_paper_id=seed_paper_id,
        strategies_succeeded=[DiscoveryStrategy.SEMANTIC, DiscoveryStrategy.CITATION],
        candidate_count_raw=12,
        candidate_count_after_dedupe=9,
        candidate_count_after_filter=len(RELATED),
    ),
)

ranked = []
candidate_paper_ids = {}
edges = []
for pid, _title, _authors, _year, _venue, rank, band, score, relationship in RELATED:
    candidate_id = f"cand_{run_id}_{rank}"
    repo.add_search_candidate(
        session,
        candidate_id=candidate_id,
        run_id=run_id,
        paper_id=pid,
        discovery_methods=[DiscoveryStrategy.SEMANTIC],
        possible_duplicate_of=None,
        provenance={"fixture": True},
        citation_relationship=CitationRelationship.NONE,
    )
    candidate_paper_ids[candidate_id] = pid
    ranked.append(
        RankedPaper(
            candidate_id=candidate_id,
            signals=SignalScores(semantic_doc=score),
            weights_version="w0-initial",
            fused_score=score,
            rerank_score=None,
            final_rank=rank,
            band=band,
            explanation=RankingExplanation(
                bullet_reasons=["strong semantic match on the core method"],
                prose="A fixture ranking explanation.",
                signals_used=["semantic_doc"],
            ),
        )
    )
    edges.append(
        TrailEdge(
            edge_id=f"edge_{run_id}_{rank}",
            run_id=run_id,
            source_paper_id=seed_paper_id,
            target_paper_id=pid,
            relationship_type=relationship,
            detection_method=DetectionMethod.RULE,
            rule_fired="playwright_fixture_rule",
            evidence=[Evidence(span=SourceSpan(paper_id=pid, quote="a fixture evidence sentence"), role="similarity_signal")],
            confidence=Confidence.MEDIUM,
        )
    )

repo.save_ranked_papers(session, run_id, ranked, candidate_paper_ids)
repo.save_trail_edges(session, run_id, edges)
session.commit()
print(f"seeded run {run_id} for {seed_paper_id}: {first_id}, {second_id}")
