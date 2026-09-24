from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.db.models import PaperORM
from app.domain.candidate import DiscoveryStrategy, NormalizedCandidate, SearchRun
from app.domain.chunk import PaperChunk
from app.domain.profile import Confidence, ProfileField, ResearchProfile, SourceSpan
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge
from app.domain.user import User
from app.domain.workspace import AddedBy, WorkspacePaperRole
from app.services.normalize.canonical import title_hash
from app.services.workspace.pipeline import (
    CannotRemoveSeed,
    PaperNotFound,
    SeedNotAnalyzed,
    WorkspaceCreateRequest,
    WorkspaceNotFound,
    add_papers,
    create_workspace,
    grouped_trail,
    remove_paper,
    update_paper,
)


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


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path, database_url="sqlite://")  # type: ignore[call-arg]


@pytest.fixture()
def owner(db: Session) -> User:
    return repo.create_user(db, user_id="usr_1", email="u@example.com")


def _seed_with_profile(db: Session, *, has_full_text: bool = True) -> str:
    row = PaperORM(
        id="pap_seed",
        title="Retrieval-Augmented Generation",
        title_hash=title_hash("Retrieval-Augmented Generation"),
        has_full_text=has_full_text,
    )
    repo.save_paper(db, row)
    if has_full_text:
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id="prof_seed",
                paper_id="pap_seed",
                title="Retrieval-Augmented Generation",
                abstract="We combine parametric and non-parametric memory.",
                domain=ProfileField(value="RAG"),
                research_problem=ProfileField(value="grounding LLM answers"),
            ),
        )
    return "pap_seed"


def _paper(db: Session, title: str) -> str:
    return repo.upsert_discovered_paper(db, NormalizedCandidate(title=title, title_hash=title_hash(title)))


def _req(**kw: object) -> WorkspaceCreateRequest:
    base: dict[str, object] = {"title": "RAG survey", "seed_paper_id": "pap_seed"}
    base.update(kw)
    return WorkspaceCreateRequest(**base)  # type: ignore[arg-type]


def test_create_workspace_seeds_with_the_analysed_paper(db: Session, owner: User, settings: Settings) -> None:
    _seed_with_profile(db)
    ws = create_workspace(db, owner=owner, req=_req(), settings=settings)
    assert ws.workspace_id.startswith("ws_")
    assert ws.seed_paper_id == "pap_seed"
    assert ws.seed_profile_id == "prof_seed"
    assert [p.role for p in ws.papers] == [WorkspacePaperRole.SEED]
    assert ws.combined_index_path is not None
    assert Path(ws.combined_index_path).exists()


def test_create_workspace_requires_an_analysed_seed(db: Session, owner: User, settings: Settings) -> None:
    _seed_with_profile(db, has_full_text=False)
    with pytest.raises(SeedNotAnalyzed):
        create_workspace(db, owner=owner, req=_req(), settings=settings)


def test_create_workspace_rejects_an_unknown_seed(db: Session, owner: User, settings: Settings) -> None:
    with pytest.raises(PaperNotFound):
        create_workspace(db, owner=owner, req=_req(seed_paper_id="pap_ghost"), settings=settings)


def test_create_workspace_ignores_an_import_run_id_that_does_not_exist(
    db: Session, owner: User, settings: Settings
) -> None:
    # `source_run_id` is a real foreign key (search_runs.run_id) -- found
    # live: a stale or otherwise-invalid run id reaching the INSERT crashed
    # with an unhandled FOREIGN KEY constraint failure (a 500) instead of
    # the workspace being created without that historical link, same as
    # when no import_run_id is given at all.
    _seed_with_profile(db)
    ws = create_workspace(db, owner=owner, req=_req(import_run_id="run_does_not_exist"), settings=settings)
    assert ws.workspace_id.startswith("ws_")
    assert ws.source_run_id is None


def test_add_papers_is_idempotent_and_rejects_unknown_ids(db: Session, owner: User, settings: Settings) -> None:
    _seed_with_profile(db)
    p1 = _paper(db, "Cand 1")
    ws = create_workspace(db, owner=owner, req=_req(), settings=settings)

    ws, added = add_papers(db, owner=owner, workspace_id=ws.workspace_id, paper_ids=[p1], settings=settings)
    assert added == [p1]
    assert {p.paper_id for p in ws.related_papers} == {p1}

    ws, added = add_papers(db, owner=owner, workspace_id=ws.workspace_id, paper_ids=[p1], settings=settings)
    assert added == []  # already a member -> no duplicate row
    assert len(ws.related_papers) == 1

    with pytest.raises(PaperNotFound):
        add_papers(db, owner=owner, workspace_id=ws.workspace_id, paper_ids=["pap_ghost"], settings=settings)


def test_add_papers_with_one_unknown_id_adds_none_of_the_batch(db: Session, owner: User, settings: Settings) -> None:
    # A batch is all-or-nothing: an unknown id used to be found mid-loop,
    # after earlier ids had already been saved -- leaving them in the
    # workspace but missing from its (never rebuilt) search index.
    _seed_with_profile(db)
    p1 = _paper(db, "Cand 1")
    ws = create_workspace(db, owner=owner, req=_req(), settings=settings)

    with pytest.raises(PaperNotFound):
        add_papers(db, owner=owner, workspace_id=ws.workspace_id, paper_ids=[p1, "pap_ghost"], settings=settings)

    ws, added = add_papers(db, owner=owner, workspace_id=ws.workspace_id, paper_ids=[], settings=settings)
    assert added == []
    assert ws.related_papers == []


def test_add_and_remove_paper_reindexes_the_workspace(db: Session, owner: User, settings: Settings) -> None:
    _seed_with_profile(db)
    p1 = _paper(db, "Cand 1")
    repo.save_chunks(
        db,
        [PaperChunk(chunk_id="chk_1", paper_id=p1, char_start=0, char_end=19, text="retrieval reranking", token_count=2)],
    )
    ws = create_workspace(db, owner=owner, req=_req(), settings=settings)
    ws, _ = add_papers(db, owner=owner, workspace_id=ws.workspace_id, paper_ids=[p1], settings=settings)

    from app.retrieval.workspace_index import load_manifest

    manifest = load_manifest(settings.data_dir / "workspace_index", ws.workspace_id)
    assert manifest is not None and p1 in manifest.paper_ids

    ws = remove_paper(db, owner=owner, workspace_id=ws.workspace_id, paper_id=p1, settings=settings)
    assert p1 not in [p.paper_id for p in ws.papers]
    manifest = load_manifest(settings.data_dir / "workspace_index", ws.workspace_id)
    assert manifest is not None and p1 not in manifest.paper_ids


def test_cannot_remove_the_seed(db: Session, owner: User, settings: Settings) -> None:
    _seed_with_profile(db)
    ws = create_workspace(db, owner=owner, req=_req(), settings=settings)
    with pytest.raises(CannotRemoveSeed):
        remove_paper(db, owner=owner, workspace_id=ws.workspace_id, paper_id="pap_seed", settings=settings)


def test_operations_on_a_foreign_workspace_raise_not_found(db: Session, owner: User, settings: Settings) -> None:
    _seed_with_profile(db)
    ws = create_workspace(db, owner=owner, req=_req(), settings=settings)
    intruder = repo.create_user(db, user_id="usr_2", email="x@example.com")
    with pytest.raises(WorkspaceNotFound):
        add_papers(db, owner=intruder, workspace_id=ws.workspace_id, paper_ids=[], settings=settings)
    with pytest.raises(WorkspaceNotFound):
        grouped_trail(db, owner=intruder, workspace_id=ws.workspace_id)


def test_update_paper_pins_tags_and_annotates(db: Session, owner: User, settings: Settings) -> None:
    _seed_with_profile(db)
    p1 = _paper(db, "Cand 1")
    ws = create_workspace(db, owner=owner, req=_req(), settings=settings)
    add_papers(db, owner=owner, workspace_id=ws.workspace_id, paper_ids=[p1], settings=settings)

    wp = update_paper(
        db,
        owner=owner,
        workspace_id=ws.workspace_id,
        paper_id=p1,
        changes={"pinned": True, "tags": [" method ", "method", "baseline"], "note": "  key ref  ", "order": 2},
    )
    assert wp.pinned is True
    assert wp.tags == ["method", "baseline"]
    assert wp.note == "key ref"
    assert wp.order == 2

    with pytest.raises(PaperNotFound):
        update_paper(db, owner=owner, workspace_id=ws.workspace_id, paper_id="pap_ghost", changes={"pinned": True})


def test_import_run_attaches_trail_and_accepts_imported_edges(db: Session, owner: User, settings: Settings) -> None:
    seed = _seed_with_profile(db)
    tgt = _paper(db, "Cand 1")
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed))
    repo.add_search_candidate(
        db, candidate_id="cand_1", run_id="run_1", paper_id=tgt,
        discovery_methods=[DiscoveryStrategy.KEYWORD], possible_duplicate_of=None, provenance={},
    )
    repo.save_ranked_papers(
        db,
        "run_1",
        [
            RankedPaper(
                candidate_id="cand_1",
                signals=SignalScores(semantic_doc=0.7),
                weights_version="w0-initial",
                fused_score=0.7,
                rerank_score=None,
                final_rank=1,
                band=Confidence.MEDIUM,
                explanation=RankingExplanation(bullet_reasons=["b"], prose="p", signals_used=["semantic_doc"]),
            )
        ],
        {"cand_1": tgt},
    )
    repo.save_trail_edges(
        db,
        "run_1",
        [
            TrailEdge(
                edge_id="edge_1", run_id="run_1", source_paper_id=seed, target_paper_id=tgt,
                relationship_type=RelationshipType.SIMILAR, detection_method=DetectionMethod.RULE,
                evidence=[Evidence(span=SourceSpan(paper_id=tgt, quote="q"), role="similarity_signal")],
                confidence=Confidence.MEDIUM,
            )
        ],
    )

    ws = create_workspace(db, owner=owner, req=_req(import_run_id="run_1"), settings=settings)
    trail = grouped_trail(db, owner=owner, workspace_id=ws.workspace_id)
    assert trail["seed_paper_id"] == seed
    assert len(trail["groups"]["SIMILAR"]) == 1

    ws, _ = add_papers(
        db, owner=owner, workspace_id=ws.workspace_id, paper_ids=[tgt], from_run_id="run_1", settings=settings
    )
    wp = ws.paper(tgt)
    assert wp is not None and wp.added_by is AddedBy.TRAIL
    assert wp.ranking_snapshot is not None and wp.ranking_snapshot.final_rank == 1
    # the imported paper's edge is now accepted (API spec §Workspaces)
    edges = repo.get_workspace_trail_edges(db, ws.workspace_id)
    assert [e.user_state for e in edges if e.target_paper_id == tgt] == ["accepted"]


def test_grouped_trail_hides_rejected_by_default(db: Session, owner: User, settings: Settings) -> None:
    seed = _seed_with_profile(db)
    tgt = _paper(db, "Cand 1")
    repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id=seed))
    repo.save_trail_edges(
        db,
        "run_1",
        [
            TrailEdge(
                edge_id="edge_1", run_id="run_1", source_paper_id=seed, target_paper_id=tgt,
                relationship_type=RelationshipType.COMPETING, detection_method=DetectionMethod.RULE,
                evidence=[Evidence(span=SourceSpan(paper_id=tgt, quote="q"), role="similarity_signal")],
                confidence=Confidence.MEDIUM, user_state="rejected",
            )
        ],
    )
    ws = create_workspace(db, owner=owner, req=_req(import_run_id="run_1"), settings=settings)

    default = grouped_trail(db, owner=owner, workspace_id=ws.workspace_id)
    assert default["groups"]["COMPETING"] == []
    shown = grouped_trail(db, owner=owner, workspace_id=ws.workspace_id, state="rejected")
    assert len(shown["groups"]["COMPETING"]) == 1
