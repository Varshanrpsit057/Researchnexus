from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.domain.candidate import NormalizedCandidate
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


def test_add_workspace_spend_accumulates_tokens_and_cost(db: Session) -> None:
    wid, uid = _workspace(db)
    repo.add_workspace_spend(db, wid, uid, tokens_prompt=100, tokens_completion=50, cost_usd=0.01)
    repo.add_workspace_spend(db, wid, uid, tokens_prompt=20, tokens_completion=10, cost_usd=0.002)
    ws = repo.get_workspace(db, wid, uid)
    assert ws is not None
    assert ws.tokens_used.prompt == 120
    assert ws.tokens_used.completion == 60
    assert round(ws.cost_used_usd, 6) == round(0.012, 6)


def test_add_workspace_spend_is_owner_gated(db: Session) -> None:
    wid, uid = _workspace(db)
    assert repo.add_workspace_spend(db, wid, "usr_other", tokens_prompt=1, tokens_completion=1, cost_usd=0.1) is None
    ws = repo.get_workspace(db, wid, uid)
    assert ws is not None and ws.cost_used_usd == 0.0
