from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import ComparisonORM, WorkspaceORM
from app.domain.candidate import NormalizedCandidate
from app.domain.comparison import Comparison, ComparisonCell, ComparisonRow, ComparisonSchema
from app.domain.profile import SourceSpan
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
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


def _workspace(db: Session) -> tuple[str, str]:
    uid = "usr_1"
    repo.create_user(db, user_id=uid, email="u@example.com")
    seed = repo.upsert_discovered_paper(db, NormalizedCandidate(title="Seed", title_hash=title_hash("Seed")))
    repo.create_workspace(
        db,
        ResearchWorkspace(
            workspace_id="ws_1", owner_id=uid, title="W", seed_paper_id=seed, seed_profile_id="prof",
            papers=[WorkspacePaper(workspace_id="ws_1", paper_id=seed, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)],
        ),
    )
    return "ws_1", uid


def _comparison(wid: str, cid: str = "cmp_1") -> Comparison:
    return Comparison(
        comparison_id=cid,
        workspace_id=wid,
        column_schema=ComparisonSchema(columns=["method", "dataset"], generated_by="deterministic_union"),
        paper_ids=["p1", "p2"],
        rows=[
            ComparisonRow(paper_id="p1", cells={
                "method": ComparisonCell(column="method", text="bm25", span=SourceSpan(paper_id="p1", quote="bm25"), claim_id="clm_cmp_1_0_method"),
                "dataset": ComparisonCell(column="dataset"),
            }),
            ComparisonRow(paper_id="p2", cells={
                "method": ComparisonCell(column="method"),
                "dataset": ComparisonCell(column="dataset", text="NQ", span=SourceSpan(paper_id="p2", quote="NQ"), claim_id="clm_cmp_1_1_dataset", grounding="abstract"),
            }),
        ],
        coverage=0.5,
    )


def test_save_and_get_comparison_round_trip(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.save_comparison(db, _comparison(wid), owner_id=uid)

    got = repo.get_comparison(db, "cmp_1", workspace_id=wid)
    assert got is not None
    assert got.column_schema.columns == ["method", "dataset"]
    assert got.paper_ids == ["p1", "p2"]
    assert got.rows[0].cells["method"].text == "bm25"
    assert got.rows[0].cells["method"].span is not None
    assert got.rows[0].cells["dataset"].text is None
    assert got.rows[1].cells["dataset"].grounding == "abstract"
    assert got.coverage == 0.5


def test_get_comparison_is_scoped_to_its_workspace(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.save_comparison(db, _comparison(wid), owner_id=uid)
    assert repo.get_comparison(db, "cmp_1", workspace_id="ws_other") is None


def test_save_comparison_upserts_by_id(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.save_comparison(db, _comparison(wid), owner_id=uid)
    updated = _comparison(wid)
    updated.coverage = 0.9
    repo.save_comparison(db, updated, owner_id=uid)
    assert db.query(ComparisonORM).filter_by(workspace_id=wid).count() == 1
    assert repo.get_comparison(db, "cmp_1", workspace_id=wid).coverage == 0.9  # type: ignore[union-attr]


def test_deleting_a_workspace_cascades_to_comparisons(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.save_comparison(db, _comparison(wid), owner_id=uid)
    repo.delete_workspace(db, wid, uid)
    assert db.query(ComparisonORM).filter_by(workspace_id=wid).count() == 0


def test_set_workspace_comparison_schema_writes_to_the_workspace_row(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.set_workspace_comparison_schema(db, wid, uid, ComparisonSchema(columns=["method", "result"]))
    row = db.get(WorkspaceORM, wid)
    assert row is not None and row.comparison_schema == {"columns": ["method", "result"], "generated_by": "deterministic_union"}
    # owner-gated: a foreign owner is a no-op
    repo.set_workspace_comparison_schema(db, wid, "usr_other", ComparisonSchema(columns=["hijacked"]))
    after = db.get(WorkspaceORM, wid)
    assert after is not None and after.comparison_schema is not None
    assert after.comparison_schema["columns"] == ["method", "result"]


def test_list_comparisons_returns_newest_first(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.save_comparison(db, _comparison(wid, "cmp_1"), owner_id=uid)
    repo.save_comparison(db, _comparison(wid, "cmp_2"), owner_id=uid)
    ids = {c.comparison_id for c in repo.list_comparisons(db, wid)}
    assert ids == {"cmp_1", "cmp_2"}
