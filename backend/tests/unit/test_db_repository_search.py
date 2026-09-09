from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import SearchCandidateORM
from app.domain.candidate import (
    DiscoveryStrategy,
    NormalizedCandidate,
    SearchRun,
)
from app.services.normalize.canonical import title_hash


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn: object, _record: object) -> None:  # SQLite needs this for ON DELETE CASCADE
        cur = dbapi_conn.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _cand(**kw: object) -> NormalizedCandidate:
    base: dict[str, object] = {"title": "A Discovered Paper", "title_hash": title_hash("A Discovered Paper")}
    base.update(kw)
    return NormalizedCandidate(**base)  # type: ignore[arg-type]


def test_upsert_discovered_paper_creates_a_discovery_sourced_row(db: Session) -> None:
    pid = repo.upsert_discovered_paper(db, _cand(external_ids={"doi": "10.5555/abc"}, year=2020, venue="NeurIPS"))
    paper = repo.get_paper(db, pid)
    assert paper is not None
    assert paper.source == "discovery"
    assert paper.has_full_text is False
    assert paper.doi == "10.5555/abc"
    assert paper.year == 2020


def test_upsert_discovered_paper_dedupes_by_doi_then_arxiv_then_title_hash(db: Session) -> None:
    first = repo.upsert_discovered_paper(db, _cand(external_ids={"doi": "10.5555/abc"}))
    # same DOI, more metadata -> same row, fields filled in
    again = repo.upsert_discovered_paper(
        db, _cand(external_ids={"doi": "10.5555/abc"}, abstract="Now with an abstract.", year=2021)
    )
    assert again == first
    paper = repo.get_paper(db, first)
    assert paper is not None
    assert paper.abstract == "Now with an abstract."
    assert paper.year == 2021

    # no DOI but same arxiv id -> still the same row
    by_arxiv = repo.upsert_discovered_paper(db, _cand(external_ids={"arxiv": "2005.11401"}))
    by_arxiv_again = repo.upsert_discovered_paper(
        db, _cand(title="Totally Different Title", title_hash=title_hash("x"), external_ids={"arxiv": "2005.11401"})
    )
    assert by_arxiv_again == by_arxiv

    # no ids at all -> dedupe on title hash
    t = repo.upsert_discovered_paper(db, _cand(title="Hash Only Paper", title_hash=title_hash("Hash Only Paper")))
    t2 = repo.upsert_discovered_paper(db, _cand(title="Hash Only Paper", title_hash=title_hash("Hash Only Paper")))
    assert t == t2


def test_upsert_discovered_paper_keeps_distinct_papers_distinct(db: Session) -> None:
    a = repo.upsert_discovered_paper(db, _cand(title="Paper A", title_hash=title_hash("Paper A")))
    b = repo.upsert_discovered_paper(db, _cand(title="Paper B", title_hash=title_hash("Paper B")))
    assert a != b


def _seed_paper(db: Session) -> str:
    return repo.upsert_discovered_paper(db, _cand(title="Seed", title_hash=title_hash("Seed")))


def test_search_run_round_trip(db: Session) -> None:
    seed_id = _seed_paper(db)
    run = SearchRun(
        run_id="run_1",
        seed_paper_id=seed_id,
        strategies_requested=[DiscoveryStrategy.KEYWORD, DiscoveryStrategy.CITATION],
        strategies_succeeded=[DiscoveryStrategy.KEYWORD],
        strategies_failed=[DiscoveryStrategy.CITATION],
        filters={"max_results": 60, "date_from": "2020-01-01"},
        candidate_count_raw=10,
        candidate_count_after_dedupe=7,
    )
    repo.create_search_run(db, run)

    fetched = repo.get_search_run(db, "run_1")
    assert fetched is not None
    assert fetched.seed_paper_id == seed_id
    assert fetched.strategies_requested == [DiscoveryStrategy.KEYWORD, DiscoveryStrategy.CITATION]
    assert fetched.strategies_failed == [DiscoveryStrategy.CITATION]
    assert fetched.filters["max_results"] == 60
    assert fetched.candidate_count_after_dedupe == 7


def test_search_candidate_round_trip_including_provenance(db: Session) -> None:
    seed_id = _seed_paper(db)
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed_id))
    paper_id = repo.upsert_discovered_paper(
        db, _cand(title="Found Paper", title_hash=title_hash("Found Paper"), authors=["A. One"], year=2022)
    )
    provenance = {
        "sources": ["arxiv", "openalex"],
        "field_provenance": [{"field": "year", "chosen_source": "openalex", "chosen_value": "2022", "rejected": ["arxiv=2021"]}],
    }
    repo.add_search_candidate(
        db,
        candidate_id="cand_1",
        run_id="run_1",
        paper_id=paper_id,
        discovery_methods=[DiscoveryStrategy.KEYWORD],
        possible_duplicate_of=None,
        provenance=provenance,
    )

    candidates = repo.get_search_candidates(db, "run_1")
    assert len(candidates) == 1
    assert candidates[0].candidate_id == "cand_1"
    assert candidates[0].title == "Found Paper"
    assert candidates[0].year == 2022
    assert candidates[0].discovery_methods == [DiscoveryStrategy.KEYWORD]

    stored_provenance = repo.get_search_candidate_provenance(db, "run_1")
    assert stored_provenance["cand_1"]["sources"] == ["arxiv", "openalex"]


def test_search_candidate_unique_per_run_and_paper(db: Session) -> None:
    seed_id = _seed_paper(db)
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed_id))
    paper_id = repo.upsert_discovered_paper(db, _cand(title="Dup", title_hash=title_hash("Dup")))
    repo.add_search_candidate(
        db, candidate_id="cand_1", run_id="run_1", paper_id=paper_id, discovery_methods=[], possible_duplicate_of=None, provenance={}
    )
    with pytest.raises(IntegrityError):
        repo.add_search_candidate(
            db, candidate_id="cand_2", run_id="run_1", paper_id=paper_id, discovery_methods=[], possible_duplicate_of=None, provenance={}
        )


def test_deleting_a_run_cascades_to_its_candidates(db: Session) -> None:
    seed_id = _seed_paper(db)
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed_id))
    paper_id = repo.upsert_discovered_paper(db, _cand(title="C", title_hash=title_hash("C")))
    repo.add_search_candidate(
        db, candidate_id="cand_1", run_id="run_1", paper_id=paper_id, discovery_methods=[], possible_duplicate_of=None, provenance={}
    )

    run_row = db.get(repo.SearchRunORM, "run_1")
    db.delete(run_row)
    db.commit()

    assert db.query(SearchCandidateORM).filter_by(run_id="run_1").count() == 0
