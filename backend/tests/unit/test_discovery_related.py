"""`assemble_related_results` (app/services/discovery/related.py) -- the
read-model behind `GET /papers/{id}/related` (Roadmap Phase 15). Pure
DB-join logic, no network and no LLM involved, mirroring the fixture style
of test_db_repository_ranking.py.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.domain.candidate import DiscoveryStrategy, NormalizedCandidate, SearchRun
from app.domain.profile import Confidence
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.services.discovery.related import RunNotFound, assemble_related_results
from app.services.normalize.canonical import title_hash


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(conn: object, _rec: object) -> None:
        cur = conn.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _ranked(candidate_id: str, rank: int, fused: float) -> RankedPaper:
    return RankedPaper(
        candidate_id=candidate_id,
        signals=SignalScores(semantic_doc=fused),
        weights_version="w0-initial",
        fused_score=fused,
        rerank_score=fused,
        final_rank=rank,
        band=Confidence.HIGH,
        explanation=RankingExplanation(bullet_reasons=["r"], prose="p."),
    )


def _seed_run(db: Session, run_id: str = "run_1") -> dict[str, str]:
    seed_id = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed")))
    repo.create_search_run(
        db,
        SearchRun(
            run_id=run_id,
            seed_paper_id=seed_id,
            strategies_succeeded=[DiscoveryStrategy.KEYWORD],
            strategies_failed=[DiscoveryStrategy.CITATION],
            candidate_count_raw=5,
            candidate_count_after_dedupe=4,
            candidate_count_after_filter=3,
        ),
    )
    ids: dict[str, str] = {}
    for i in range(3):
        pid = repo.upsert_discovered_paper(
            db, NormalizedCandidate(title=f"Cand {i}", title_hash=title_hash(f"Cand {i}"))
        )
        cid = f"cand_{i}"
        repo.add_search_candidate(
            db,
            candidate_id=cid,
            run_id=run_id,
            paper_id=pid,
            discovery_methods=[DiscoveryStrategy.KEYWORD],
            possible_duplicate_of=None,
            provenance={},
        )
        ids[cid] = pid
    return ids


def test_assemble_joins_candidates_with_ranking_ranked_first(db: Session) -> None:
    ids = _seed_run(db)
    repo.save_ranked_papers(db, "run_1", [_ranked("cand_2", 1, 0.9), _ranked("cand_0", 2, 0.5)], ids)

    view = assemble_related_results(db, "run_1")

    assert view.run_id == "run_1"
    assert view.counts == {"raw": 5, "after_dedupe": 4, "after_filter": 3, "off_topic": 0}
    assert view.strategies_succeeded == ["keyword"]
    assert view.strategies_failed == ["citation"]
    assert view.weights_version == "w0-initial"

    # Ranked results come first, ordered by final_rank; the unranked
    # candidate (rank pending) is present but sorts after them.
    assert [r.paper_id for r in view.results] == [ids["cand_2"], ids["cand_0"], ids["cand_1"]]
    assert view.results[0].ranking is not None
    assert view.results[0].ranking.final_rank == 1
    assert view.results[2].ranking is None


def test_assemble_excludes_candidates_filtered_out_by_discovery(db: Session) -> None:
    seed_id = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed")))
    repo.create_search_run(db, SearchRun(run_id="run_2", seed_paper_id=seed_id))
    kept_pid = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Kept", title_hash=title_hash("Kept")))
    dropped_pid = repo.upsert_discovered_paper(
        db, NormalizedCandidate(title="Dropped", title_hash=title_hash("Dropped"))
    )
    repo.add_search_candidate(
        db,
        candidate_id="cand_kept",
        run_id="run_2",
        paper_id=kept_pid,
        discovery_methods=[DiscoveryStrategy.KEYWORD],
        possible_duplicate_of=None,
        provenance={},
    )
    repo.add_search_candidate(
        db,
        candidate_id="cand_dropped",
        run_id="run_2",
        paper_id=dropped_pid,
        discovery_methods=[DiscoveryStrategy.KEYWORD],
        possible_duplicate_of=None,
        provenance={},
        filter_kept=False,
        filter_reasons=["too_old"],
    )

    view = assemble_related_results(db, "run_2")

    assert [r.paper_id for r in view.results] == [kept_pid]


def test_assemble_raises_run_not_found_for_a_missing_run(db: Session) -> None:
    with pytest.raises(RunNotFound):
        assemble_related_results(db, "run_ghost")
