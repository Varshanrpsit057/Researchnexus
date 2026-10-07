"""Playwright test helper (remediation Phase 8): discover jobs and a saved run
in the states the discovery page has to show, written through the backend's
own code -- the progress and the run report come from the real
DiscoveryProgress tracker fed the events a run produces, the failure text
from the real job runner, and every row through the repository -- so the
page reads exactly what a real run writes. A real run's external sources
(rate limits, a seed missing from OpenAlex) can't be had on demand; the job
endpoints, cancellation, resuming and the results page are all real.

Usage:
  python seed-discover-job.py running <seed_paper_id> <email>    -> prints the job id
  python seed-discover-job.py advance <job_id>                   (on to the rank step)
  python seed-discover-job.py stale <seed_paper_id> <email>      -> a running job last heard from 2 min ago
  python seed-discover-job.py failed <seed_paper_id> <email>     -> a job that failed, with its reason
  python seed-discover-job.py run <seed_paper_id> <run_id> <first_id> <second_id>  -> a partial saved run
  python seed-discover-job.py ranked-run <seed_paper_id> <run_id> <cited_id> <recent_id>  -> ranked by the real pipeline
  python seed-discover-job.py cleanup <job_id> [<job_id> ...]
"""

import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, r"H:\Researchnexus\backend")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository as repo
from app.db.models import JobORM, PaperORM
from app.domain.candidate import CandidateSource, CitationRelationship, DiscoveryStrategy, RawExternalRecord, SearchRun
from app.domain.jobs import Job, JobKind, JobStatus
from app.domain.profile import Confidence
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.jobs.runner import _discovery_failure, new_id
from app.services.discovery.progress import DiscoveryProgress

engine = create_engine(r"sqlite:///H:/Researchnexus/backend/data/researchnexus.db")
session = sessionmaker(bind=engine)()

ARRIVED = [
    RawExternalRecord(source=CandidateSource.SEMANTIC_SCHOLAR, doi=f"10.5555/pw-p8-{i}", title=title, year=2023)
    for i, title in enumerate(
        [
            "Phase 8 Fixture: Retrieval Signals for Related Work",
            "Phase 8 Fixture: Citation Neighbourhoods at Scale",
            "Phase 8 Fixture: Ranking Papers Against a Seed",
        ]
    )
]


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def replay(until: str) -> DiscoveryProgress:
    """The events of a run whose seed is on Semantic Scholar only, while
    Semantic Scholar rate-limits half its requests, up to `until`."""
    clock = _Clock()
    p = DiscoveryProgress(clock=clock)
    p.begin("plan")
    p.begin("resolve", limit_s=15)
    clock.t += 0.2
    p.end("plan", note="fallback")
    clock.t += 2.3
    p.end("resolve", note="found on Semantic Scholar; OpenAlex couldn't be asked")
    p.begin("search", limit_s=30)
    for name in (DiscoveryStrategy.KEYWORD, DiscoveryStrategy.QUERY_EXPANSION, DiscoveryStrategy.CITATION, DiscoveryStrategy.RECOMMENDATION):
        p.strategy_started(name)
    for _ in range(3):
        p.on_request("www.ebi.ac.uk", "ok", 1.8)
    for outcome in ("ok", "rate_limited", "ok", "rate_limited", "ok", "rate_limited", "ok", "rate_limited"):
        p.on_request("api.semanticscholar.org", outcome, 1.0)
    p.on_request("api.openalex.org", "rate_limited", 0.9)
    clock.t += 3.1
    p.found(DiscoveryStrategy.RECOMMENDATION, ARRIVED[:2])
    p.found(DiscoveryStrategy.KEYWORD, ARRIVED)
    p.strategy_finished(DiscoveryStrategy.RECOMMENDATION, state="done", found=2, notes=["recommendation_openalex_failed"])
    if until == "search":
        return p
    clock.t += 26.9
    p.strategy_finished(DiscoveryStrategy.KEYWORD, state="done", found=3)
    p.strategy_finished(DiscoveryStrategy.QUERY_EXPANSION, state="done", found=0, notes=["query_expansion_all_sources_failed"])
    p.strategy_finished(DiscoveryStrategy.CITATION, state="timed_out", found=12, notes=["citation_timed_out"])
    p.end("search", found=p.distinct_found)
    p.warn("strategy_timeout:citation", "budget_truncated")
    p.begin("score", limit_s=30, total=3)
    clock.t += 1.2
    p.end("score")
    p.begin("save", total=2)
    clock.t += 0.1
    p.end("save")
    if until == "save":
        return p
    p.begin("rank")
    return p


def _owner(email: str) -> str:
    user = repo.get_user_by_email(session, email)
    assert user is not None, f"no user {email}: sign in once first"
    return user.id


def _job(email: str, seed: str, status: JobStatus, progress: dict, error: str | None = None) -> str:
    job_id = new_id("job")
    repo.create_job(session, Job(job_id=job_id, owner_id=_owner(email), kind=JobKind.DISCOVER, status=status, progress={**progress, "seed_paper_id": seed}, error=error))
    return job_id


mode = sys.argv[1]
if mode == "running":
    print(_job(sys.argv[3], sys.argv[2], JobStatus.RUNNING, replay("search").snapshot()))
elif mode == "advance":
    repo.update_job(session, sys.argv[2], status=JobStatus.RUNNING, progress=replay("rank").snapshot())
elif mode == "stale":
    job_id = _job(sys.argv[3], sys.argv[2], JobStatus.RUNNING, replay("search").snapshot())
    session.query(JobORM).filter(JobORM.id == job_id).update(
        {JobORM.updated_at: datetime.now(timezone.utc) - timedelta(minutes=2)}, synchronize_session=False
    )
    session.commit()
    print(job_id)
elif mode == "failed":
    progress = replay("search")
    message = _discovery_failure("discovery", RuntimeError("every source refused the request"))
    progress.end("search", state="failed", note=message)
    print(_job(sys.argv[3], sys.argv[2], JobStatus.FAILED, {**progress.snapshot(), "stage": "failed"}, error=message))
elif mode == "run":
    seed, run_id, first_id, second_id = sys.argv[2:6]
    related = [
        (first_id, "Phase 8 Fixture: Retrieval Signals for Related Work", 1, Confidence.HIGH, 0.81, CitationRelationship.CITES_SEED),
        (second_id, "Phase 8 Fixture: Citation Neighbourhoods at Scale", 2, Confidence.MEDIUM, 0.58, CitationRelationship.NONE),
    ]
    for pid, title, *_ in related:
        if session.get(PaperORM, pid) is None:
            session.add(PaperORM(id=pid, title=title, title_hash=f"pw-phase8-{pid}", authors=["P. Fixture"], year=2023, has_full_text=False, source="discovery"))
    session.commit()
    report = replay("save").report()
    report["status"] = "partial"
    report["strategies_timed_out"] = ["citation"]
    repo.create_search_run(
        session,
        SearchRun(
            run_id=run_id,
            seed_paper_id=seed,
            strategies_requested=[DiscoveryStrategy.KEYWORD, DiscoveryStrategy.QUERY_EXPANSION, DiscoveryStrategy.CITATION, DiscoveryStrategy.RECOMMENDATION],
            strategies_succeeded=[DiscoveryStrategy.KEYWORD, DiscoveryStrategy.QUERY_EXPANSION, DiscoveryStrategy.CITATION, DiscoveryStrategy.RECOMMENDATION],
            candidate_count_raw=17,
            candidate_count_after_dedupe=14,
            candidate_count_after_filter=2,
            report=report,
        ),
    )
    ranked, paper_ids = [], {}
    for pid, _title, rank, band, score, rel in related:
        candidate_id = f"cand_{run_id.removeprefix('run_')}_{rank:04d}"
        repo.add_search_candidate(
            session, candidate_id=candidate_id, run_id=run_id, paper_id=pid,
            discovery_methods=[DiscoveryStrategy.CITATION if rel is CitationRelationship.CITES_SEED else DiscoveryStrategy.KEYWORD],
            possible_duplicate_of=None, provenance={"fixture": True}, citation_relationship=rel,
        )
        paper_ids[candidate_id] = pid
        ranked.append(
            RankedPaper(
                candidate_id=candidate_id, signals=SignalScores(semantic_doc=score), weights_version="w0-initial",
                fused_score=score, rerank_score=None, final_rank=rank, band=band,
                explanation=RankingExplanation(bullet_reasons=["a fixture reason"], prose="A fixture ranking explanation.", signals_used=["semantic_doc"]),
            )
        )
    repo.save_ranked_papers(session, run_id, ranked, paper_ids)
    print(run_id)
elif mode == "ranked-run":
    # two candidates ranked by the real ranking pipeline (no relevance model:
    # the citation and recency signals decide), for the ranking-controls spec
    import asyncio

    from app.config import Settings
    from app.domain.candidate import NormalizedCandidate
    from app.services.normalize.canonical import title_hash
    from app.services.ranking.pipeline import RankOptions, rank_search_run

    seed, run_id, cited_id, recent_id = sys.argv[2:6]
    repo.create_search_run(session, SearchRun(run_id=run_id, seed_paper_id=seed, strategies_succeeded=[DiscoveryStrategy.CITATION, DiscoveryStrategy.KEYWORD]))
    specs = [
        (cited_id, "Phase 9 Fixture: An Older Paper The Seed Cites", 2012, CitationRelationship.CITED_BY_SEED),
        (recent_id, "Phase 9 Fixture: A Brand New Paper", 2026, CitationRelationship.NONE),
    ]
    for position, (pid, title, year, rel) in enumerate(specs, start=1):
        if session.get(PaperORM, pid) is None:
            session.add(PaperORM(id=pid, title=title, title_hash=f"pw-phase9-{pid}", authors=["P. Fixture"], year=year, has_full_text=False, source="discovery"))
            session.commit()
        repo.add_search_candidate(
            session, candidate_id=f"cand_{run_id.removeprefix('run_')}_{position:04d}", run_id=run_id, paper_id=pid,
            discovery_methods=[DiscoveryStrategy.CITATION if rel is CitationRelationship.CITED_BY_SEED else DiscoveryStrategy.KEYWORD],
            possible_duplicate_of=None, provenance={"fixture": True}, citation_relationship=rel,
            citation_hops=1 if rel is CitationRelationship.CITED_BY_SEED else None,
        )
    asyncio.run(rank_search_run(session, run_id=run_id, settings=Settings(), options=RankOptions()))
    print(run_id)
elif mode == "cleanup":
    session.query(JobORM).filter(JobORM.id.in_(sys.argv[2:])).delete(synchronize_session=False)
    session.commit()
else:
    raise SystemExit(f"unknown mode {mode}")
