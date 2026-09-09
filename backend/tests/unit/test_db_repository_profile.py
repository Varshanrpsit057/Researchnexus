from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import repository as repo
from app.db.base import Base
from app.domain.profile import Confidence, ProfileField, ResearchProfile


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()


def _profile(**overrides: object) -> ResearchProfile:
    kwargs: dict[str, object] = {
        "profile_id": "prof_1",
        "paper_id": "pap_1",
        "title": "A Paper",
        "abstract": "An abstract.",
        "domain": ProfileField(value="NLP"),
        "research_problem": ProfileField(value="Solving Y"),
        "extraction_confidence": Confidence.MEDIUM,
        "extraction_model": "groq:llama-3.1-8b-instant",
    }
    kwargs.update(overrides)
    return ResearchProfile(**kwargs)  # type: ignore[arg-type]


def test_upsert_then_get_profile_round_trips(db: Session) -> None:
    profile = _profile()
    repo.upsert_profile(db, profile)

    fetched = repo.get_profile(db, "pap_1")
    assert fetched is not None
    assert fetched.profile_id == "prof_1"
    assert fetched.domain.value == "NLP"
    assert fetched.extraction_confidence == Confidence.MEDIUM
    assert fetched.extraction_model == "groq:llama-3.1-8b-instant"


def test_upsert_twice_updates_the_same_row_not_a_duplicate(db: Session) -> None:
    repo.upsert_profile(db, _profile())
    repo.upsert_profile(db, _profile(domain=ProfileField(value="Computer Vision")))

    fetched = repo.get_profile(db, "pap_1")
    assert fetched is not None
    assert fetched.domain.value == "Computer Vision"


def test_get_profile_returns_none_when_missing(db: Session) -> None:
    assert repo.get_profile(db, "pap_does_not_exist") is None


def test_profile_scoped_by_workspace_id(db: Session) -> None:
    canonical = _profile(workspace_id=None)
    workspace_scoped = _profile(profile_id="prof_2", workspace_id="ws_1")
    repo.upsert_profile(db, canonical)
    repo.upsert_profile(db, workspace_scoped)

    assert repo.get_profile(db, "pap_1", workspace_id=None) is not None
    assert repo.get_profile(db, "pap_1", workspace_id=None).profile_id == "prof_1"  # type: ignore[union-attr]
    assert repo.get_profile(db, "pap_1", workspace_id="ws_1").profile_id == "prof_2"  # type: ignore[union-attr]
