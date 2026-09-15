"""Read-model for `GET /papers/{id}/related` (Roadmap Phase 15: the first
HTTP-reachable view of Phase 5/6 discovery+ranking results). Joins
`search_candidates` and `ranked_papers` by `candidate_id` -- both already
persisted by `run_discovery`/`rank_search_run`, unchanged by this module.
Never invents a value: a missing rank/signal stays absent, never zeroed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.db import repository as repo
from app.domain.candidate import PaperCandidate
from app.domain.ranking import RankedPaper


@dataclass
class RelatedResult:
    paper_id: str
    candidate: PaperCandidate
    ranking: RankedPaper | None


@dataclass
class RelatedResultsView:
    run_id: str
    seed_paper_id: str
    strategies_succeeded: list[str]
    strategies_failed: list[str]
    counts: dict[str, int]
    extra_citation_hop_used: bool
    weights_version: str | None
    results: list[RelatedResult] = field(default_factory=list)


class RunNotFound(Exception):
    pass


def assemble_related_results(db: Session, run_id: str) -> RelatedResultsView:
    run = repo.get_search_run(db, run_id)
    if run is None:
        raise RunNotFound(run_id)

    candidates = {c.candidate_id: c for c in repo.get_search_candidates(db, run_id)}
    paper_ids = repo.get_search_candidate_paper_ids(db, run_id)
    ranked_by_candidate = {r.candidate_id: r for r in repo.get_ranked_papers(db, run_id)}

    results: list[RelatedResult] = []
    for candidate_id, candidate in candidates.items():
        paper_id = paper_ids.get(candidate_id)
        if paper_id is None or not candidate.filter_kept:
            continue
        results.append(RelatedResult(paper_id=paper_id, candidate=candidate, ranking=ranked_by_candidate.get(candidate_id)))

    # Ranked first (by final_rank), unranked candidates (rank pending) after.
    results.sort(key=lambda r: (r.ranking is None, r.ranking.final_rank if r.ranking else 0))

    weights_version = next((r.ranking.weights_version for r in results if r.ranking), None)

    return RelatedResultsView(
        run_id=run_id,
        seed_paper_id=run.seed_paper_id,
        strategies_succeeded=[s.value for s in run.strategies_succeeded],
        strategies_failed=[s.value for s in run.strategies_failed],
        counts={
            "raw": run.candidate_count_raw,
            "after_dedupe": run.candidate_count_after_dedupe,
            "after_filter": run.candidate_count_after_filter,
        },
        extra_citation_hop_used=run.extra_citation_hop_used,
        weights_version=weights_version,
        results=results,
    )
