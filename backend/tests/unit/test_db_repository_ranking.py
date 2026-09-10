from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import RankedPaperORM
from app.domain.candidate import DiscoveryStrategy, NormalizedCandidate, SearchRun
from app.domain.profile import Confidence
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
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


def _setup_run(db: Session) -> tuple[str, dict[str, str]]:
    seed_id = repo.upsert_discovered_paper(
        db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed"))
    )
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed_id))
    ids: dict[str, str] = {}
    for i in range(3):
        pid = repo.upsert_discovered_paper(
            db, NormalizedCandidate(title=f"Cand {i}", title_hash=title_hash(f"Cand {i}"))
        )
        cid = f"cand_{i}"
        repo.add_search_candidate(
            db, candidate_id=cid, run_id="run_1", paper_id=pid, discovery_methods=[DiscoveryStrategy.KEYWORD],
            possible_duplicate_of=None, provenance={},
        )
        ids[cid] = pid
    return "run_1", ids


def _ranked(candidate_id: str, rank: int, fused: float, band: Confidence) -> RankedPaper:
    return RankedPaper(
        candidate_id=candidate_id,
        signals=SignalScores(semantic_doc=fused, citation=0.6),
        weights_version="w0-initial",
        fused_score=fused,
        rerank_score=fused - 0.05,
        final_rank=rank,
        band=band,
        explanation=RankingExplanation(bullet_reasons=[f"reason {rank}"], prose="p.", signals_used=["semantic_doc"]),
    )


def test_save_and_get_ranked_papers_round_trip(db: Session) -> None:
    run_id, ids = _setup_run(db)
    ranked = [
        _ranked("cand_0", 1, 0.9, Confidence.HIGH),
        _ranked("cand_1", 2, 0.5, Confidence.MEDIUM),
        _ranked("cand_2", 3, 0.2, Confidence.LOW),
    ]
    repo.save_ranked_papers(db, run_id, ranked, ids)

    fetched = repo.get_ranked_papers(db, run_id)
    assert [r.final_rank for r in fetched] == [1, 2, 3]
    assert fetched[0].candidate_id == "cand_0"
    assert fetched[0].band == Confidence.HIGH
    assert fetched[0].signals.semantic_doc == 0.9
    assert fetched[0].explanation.bullet_reasons == ["reason 1"]
    assert fetched == ranked


def test_re_ranking_replaces_the_previous_result(db: Session) -> None:
    run_id, ids = _setup_run(db)
    repo.save_ranked_papers(db, run_id, [_ranked("cand_0", 1, 0.9, Confidence.HIGH)], ids)
    repo.save_ranked_papers(db, run_id, [_ranked("cand_1", 1, 0.8, Confidence.HIGH)], ids)

    fetched = repo.get_ranked_papers(db, run_id)
    assert len(fetched) == 1
    assert fetched[0].candidate_id == "cand_1"


def test_deleting_a_run_cascades_to_its_ranked_papers(db: Session) -> None:
    run_id, ids = _setup_run(db)
    repo.save_ranked_papers(db, run_id, [_ranked("cand_0", 1, 0.9, Confidence.HIGH)], ids)

    run_row = db.get(repo.SearchRunORM, run_id)
    db.delete(run_row)
    db.commit()

    assert db.query(RankedPaperORM).filter_by(run_id=run_id).count() == 0


def test_get_search_candidate_paper_ids_maps_candidates_to_papers(db: Session) -> None:
    run_id, ids = _setup_run(db)
    assert repo.get_search_candidate_paper_ids(db, run_id) == ids
