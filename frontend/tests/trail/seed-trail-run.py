"""Playwright test helper (Phase 7): a completed discovery run whose trail
is built by the REAL trail pipeline (app/services/trail/pipeline.py).

Discovery can't reach arXiv/OpenAlex/S2 here, so this persists the run's
inputs the way the discover/rank stages would -- four candidate papers with
abstracts, citation links to the seed, and measured ranking signals -- and
then calls `build_trail` itself. Every rule, evidence span and confidence
on the resulting edges comes from production code, not from this file:

- "A paper about topic 1" is cited by the seed and older -> FOUNDATIONAL,
  quoting the seed PDF's own reference entry for it;
- a paper 82% similar overall -> SIMILAR, quoting its abstract;
- a paper that cites the seed with a 66%-similar method -> METHOD_EXTENSION;
- same problem, different method, no citation -> COMPETING.

The seed's research problem and method are given source spans taken
verbatim from its parsed text, and its year is set so the year-based rule
can fire (`restore` puts the year back).

Usage:
  python seed-trail-run.py seed <seed_paper_id> <run_id> <tag>
  python seed-trail-run.py restore <seed_paper_id>
"""

import asyncio
import json
import re
import sys

sys.path.insert(0, r"H:\Researchnexus\backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.models import PaperORM
from app.domain.candidate import CitationRelationship, DiscoveryStrategy, SearchRun
from app.domain.profile import Confidence, ProfileField, ProfileList, SourceSpan
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.services.trail.pipeline import TrailOptions, build_trail

SEED_YEAR = 2021

engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
session = sessionmaker(bind=engine)()

mode, seed_id = sys.argv[1], sys.argv[2]
seed = session.get(PaperORM, seed_id)
assert seed is not None, f"no seed paper {seed_id}"

if mode == "restore":
    seed.year = None
    session.commit()
    print(f"restored {seed_id}")
    sys.exit(0)

run_id, tag = sys.argv[3], sys.argv[4]
seed.year = SEED_YEAR
session.commit()

# A verbatim sentence from the seed's own parsed text, for its claim spans.
sentence, section = None, None
for chunk in repo.get_chunks_for_paper(session, seed_id):
    m = re.search(r"Retrieval augmented generation combines[^.]*\.", chunk.text)
    if m:
        sentence, section = m.group(0), chunk.section
        break
assert sentence, "the seed's text lacks the expected sentence"
span = SourceSpan(paper_id=seed_id, section=section, quote=sentence[:400])

profile = repo.get_profile(session, seed_id)
assert profile is not None, "seed the profile first (seed-real-profile.py)"
repo.upsert_profile(
    session,
    profile.model_copy(
        update={
            "research_problem": ProfileField(
                value="retrieval augmented generation reduces hallucination and improves factual grounding", source_span=span
            ),
            "methods": ProfileList(items=[ProfileField(value="dense retrieval with a parametric generator", source_span=span)]),
        }
    ),
)

CANDIDATES = [
    # title, abstract, year, citation relationship, signals
    (
        "A paper about topic 1",
        "An early study of topic 1 that later retrieval work builds on. "
        "We analyse retrieval augmented generation in a controlled setting and report its failure modes.",
        2018,
        CitationRelationship.CITED_BY_SEED,
        SignalScores(semantic_doc=0.55),
    ),
    (
        "Phase 7 Fixture: Retrieval-Augmented Generators Revisited",
        "We revisit generators that read retrieved passages. "
        "Our study shows that retrieval augmented generation reduces hallucination and improves factual grounding on knowledge intensive tasks. "
        "Code is released.",
        SEED_YEAR,
        CitationRelationship.NONE,
        SignalScores(semantic_doc=0.82, problem_sim=0.7, method_sim=0.5),
    ),
    (
        "Phase 7 Fixture: Extending Parametric Memory with Dense Retrievers",
        "We extend dense retrieval with a parametric generator for multi-hop questions. Results improve on three benchmarks.",
        2022,
        CitationRelationship.CITES_SEED,
        SignalScores(method_sim=0.66, semantic_doc=0.3, problem_sim=0.3),
    ),
    (
        "Phase 7 Fixture: A Competing Symbolic Approach",
        "We address hallucination in knowledge intensive tasks with symbolic reasoning instead of retrieval. "
        "A rule engine verifies each generated claim.",
        SEED_YEAR,
        CitationRelationship.NONE,
        SignalScores(problem_sim=0.62, method_sim=0.2, semantic_doc=0.4),
    ),
]

repo.create_search_run(
    session,
    SearchRun(
        run_id=run_id,
        seed_paper_id=seed_id,
        strategies_succeeded=[DiscoveryStrategy.SEMANTIC, DiscoveryStrategy.CITATION],
        candidate_count_raw=len(CANDIDATES),
        candidate_count_after_dedupe=len(CANDIDATES),
        candidate_count_after_filter=len(CANDIDATES),
    ),
)
ranked, paper_of = [], {}
for rank, (title, abstract, year, rel, signals) in enumerate(CANDIDATES, start=1):
    pid = f"pap_pw_trail_{tag}_{rank}"
    session.add(
        PaperORM(
            id=pid, title=title, title_hash=f"pw-trail-{tag}-{rank}", authors=["T. Fixture"], year=year,
            abstract=abstract, has_full_text=False, source="discovery", sections=[], tables=[], references=[], warnings=[],
        )
    )
    session.commit()
    cid = f"cand_{run_id}_{rank}"
    repo.add_search_candidate(
        session, candidate_id=cid, run_id=run_id, paper_id=pid, discovery_methods=[DiscoveryStrategy.SEMANTIC],
        possible_duplicate_of=None, provenance={"fixture": True}, citation_relationship=rel,
        citation_hops=1 if rel is not CitationRelationship.NONE else None,
    )
    paper_of[cid] = pid
    ranked.append(
        RankedPaper(
            candidate_id=cid, signals=signals, weights_version="w0-initial", fused_score=1 / rank, rerank_score=None,
            final_rank=rank, band=Confidence.MEDIUM,
            explanation=RankingExplanation(bullet_reasons=["fixture"], prose="fixture", signals_used=[]),
        )
    )
repo.save_ranked_papers(session, run_id, ranked, paper_of)

result = asyncio.run(build_trail(session, run_id=run_id, settings=Settings(_env_file=None), options=TrailOptions()))
edges = repo.get_trail_edges(session, run_id)
print(json.dumps({"edges": result.edge_count, "types": sorted(e.relationship_type.value for e in edges)}))
