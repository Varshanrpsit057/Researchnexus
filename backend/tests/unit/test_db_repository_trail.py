from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperRelationshipORM
from app.domain.candidate import NormalizedCandidate, SearchRun
from app.domain.profile import Confidence, SourceSpan
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge, UserState
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


def _setup(db: Session) -> tuple[str, str, str]:
    seed = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed")))
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed))
    tgt = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Target", title_hash=title_hash("Target")))
    return "run_1", seed, tgt


def _edge(run_id: str, seed: str, tgt: str, rtype: RelationshipType, *, edge_id: str = "edge_1") -> TrailEdge:
    return TrailEdge(
        edge_id=edge_id,
        run_id=run_id,
        source_paper_id=seed,
        target_paper_id=tgt,
        relationship_type=rtype,
        detection_method=DetectionMethod.RULE,
        rule_fired="a rule",
        evidence=[Evidence(span=SourceSpan(paper_id=tgt, quote="a supporting sentence"), role="target_claim")],
        confidence=Confidence.MEDIUM,
        confidence_basis={"signal_agreement": 2},
    )


def test_save_and_get_trail_edges_round_trip(db: Session) -> None:
    run_id, seed, tgt = _setup(db)
    repo.save_trail_edges(db, run_id, [_edge(run_id, seed, tgt, RelationshipType.SIMILAR)])

    edges = repo.get_trail_edges(db, run_id)
    assert len(edges) == 1
    e = edges[0]
    assert e.relationship_type == RelationshipType.SIMILAR
    assert e.rule_fired == "a rule"
    assert e.evidence[0].role == "target_claim"
    assert e.confidence_basis["signal_agreement"] == 2
    assert e.user_state == "pending"


def test_resaving_updates_pending_edges_and_removes_dropped_ones(db: Session) -> None:
    run_id, seed, tgt = _setup(db)
    repo.save_trail_edges(
        db,
        run_id,
        [
            _edge(run_id, seed, tgt, RelationshipType.SIMILAR, edge_id="edge_sim"),
            _edge(run_id, seed, tgt, RelationshipType.DATASET_RELATED, edge_id="edge_ds"),
        ],
    )
    # a re-run that no longer produces the DATASET_RELATED edge
    repo.save_trail_edges(db, run_id, [_edge(run_id, seed, tgt, RelationshipType.SIMILAR, edge_id="edge_sim")])
    kinds = {e.relationship_type for e in repo.get_trail_edges(db, run_id)}
    assert kinds == {RelationshipType.SIMILAR}


def test_a_rejected_edge_is_preserved_and_its_key_is_reported(db: Session) -> None:
    run_id, seed, tgt = _setup(db)
    repo.save_trail_edges(db, run_id, [_edge(run_id, seed, tgt, RelationshipType.COMPETING, edge_id="edge_c")])
    repo.set_trail_edge_user_state(db, "edge_c", UserState.REJECTED)

    # a re-run that produces no edges at all
    repo.save_trail_edges(db, run_id, [])
    surviving = repo.get_trail_edges(db, run_id)
    assert [e.user_state for e in surviving] == ["rejected"]
    assert repo.get_rejected_trail_keys(db, run_id) == {(tgt, "COMPETING")}


def test_set_user_state_accept(db: Session) -> None:
    run_id, seed, tgt = _setup(db)
    repo.save_trail_edges(db, run_id, [_edge(run_id, seed, tgt, RelationshipType.RECENT, edge_id="edge_r")])
    updated = repo.set_trail_edge_user_state(db, "edge_r", UserState.ACCEPTED)
    assert updated is not None and updated.user_state == "accepted"
    assert repo.set_trail_edge_user_state(db, "edge_missing", UserState.ACCEPTED) is None


def test_deleting_a_run_cascades_to_its_trail_edges(db: Session) -> None:
    run_id, seed, tgt = _setup(db)
    repo.save_trail_edges(db, run_id, [_edge(run_id, seed, tgt, RelationshipType.SIMILAR)])
    db.delete(db.get(repo.SearchRunORM, run_id))
    db.commit()
    assert db.query(PaperRelationshipORM).filter_by(run_id=run_id).count() == 0


def test_unique_constraint_on_run_source_target_type(db: Session) -> None:
    run_id, seed, tgt = _setup(db)
    repo.save_trail_edges(db, run_id, [_edge(run_id, seed, tgt, RelationshipType.SIMILAR, edge_id="edge_a")])
    # same (run, source, target, type) but a different edge_id -> the second insert must be rejected
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db.add(
            PaperRelationshipORM(
                id="edge_b",
                run_id=run_id,
                source_paper_id=seed,
                target_paper_id=tgt,
                relationship_type="SIMILAR",
                detection_method="rule",
                confidence="low",
            )
        )
        db.commit()
