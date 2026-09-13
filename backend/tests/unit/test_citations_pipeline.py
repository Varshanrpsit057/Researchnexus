from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperORM
from app.domain.workspace import AddedBy, ResearchWorkspace, WorkspacePaper, WorkspacePaperRole
from app.services.citations.pipeline import build_citations
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


def _workspace(db: Session, *, extra_paper: bool = True) -> tuple[ResearchWorkspace, str]:
    uid = "usr_1"
    repo.create_user(db, user_id=uid, email="u@example.com")
    seed = "pap_seed"
    repo.save_paper(db, PaperORM(id=seed, title="Seed Paper", title_hash=title_hash("Seed Paper"), doi="10.1/seed", has_full_text=True))
    papers = [WorkspacePaper(workspace_id="ws_1", paper_id=seed, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED)]
    if extra_paper:
        repo.save_paper(db, PaperORM(id="pap_a", title="Paper A", title_hash=title_hash("Paper A"), has_full_text=True))
        papers.append(WorkspacePaper(workspace_id="ws_1", paper_id="pap_a", added_by=AddedBy.MANUAL, role=WorkspacePaperRole.RELATED))
    ws = ResearchWorkspace(workspace_id="ws_1", owner_id=uid, title="W", seed_paper_id=seed, seed_profile_id="prof", papers=papers)
    repo.create_workspace(db, ws)
    return repo.get_workspace(db, "ws_1", uid), uid  # type: ignore[return-value]


def test_builds_a_citation_for_every_workspace_paper_by_default(db: Session) -> None:
    ws, uid = _workspace(db)
    result = build_citations(db, workspace=ws, paper_ids=None, formats=["apa", "ieee", "bibtex"], owner_id=uid)
    assert {c["paper_id"] for c in result.citations} == {"pap_seed", "pap_a"}
    # pap_seed has a DOI and resolves; pap_a has none of the identifiers
    # metadata_resolver.resolve_paper needs, so it is legitimately unresolved.
    assert result.unresolved == ["pap_a"]


def test_can_scope_to_a_subset_of_paper_ids(db: Session) -> None:
    ws, uid = _workspace(db)
    result = build_citations(db, workspace=ws, paper_ids=["pap_a"], formats=["apa"], owner_id=uid)
    assert [c["paper_id"] for c in result.citations] == ["pap_a"]


def test_a_paper_id_outside_the_workspace_is_ignored(db: Session) -> None:
    ws, uid = _workspace(db)
    result = build_citations(db, workspace=ws, paper_ids=["pap_ghost"], formats=["apa"], owner_id=uid)
    assert result.citations == []


def test_formats_default_to_all_three_when_none_are_recognised(db: Session) -> None:
    ws, uid = _workspace(db, extra_paper=False)
    result = build_citations(db, workspace=ws, paper_ids=None, formats=["not_a_format"], owner_id=uid)
    assert set(result.citations[0]["formatted"]) == {"apa", "ieee", "bibtex"}


def test_citations_are_persisted(db: Session) -> None:
    ws, uid = _workspace(db, extra_paper=False)
    build_citations(db, workspace=ws, paper_ids=None, formats=["apa"], owner_id=uid)
    stored = repo.get_citations(db, "ws_1")
    assert len(stored) == 1 and stored[0].paper_id == "pap_seed"
