from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.domain.candidate import NormalizedCandidate
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.comparison import ComparisonSchema
from app.domain.user import LlmProvider
from app.domain.workspace import (
    AddedBy,
    Grounding,
    ResearchWorkspace,
    WorkspacePaper,
    WorkspacePaperRole,
)
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.retrieval.workspace_index import FaissWorkspaceIndex
from app.services.normalize.canonical import title_hash
from app.services.synthesis.compare import build_comparison


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


def _paper(db: Session, title: str, chunks: list[tuple[str, str]]) -> str:
    pid = repo.upsert_discovered_paper(db, NormalizedCandidate(title=title, title_hash=title_hash(title)))
    repo.save_chunks(
        db,
        [
            PaperChunk(chunk_id=cid, paper_id=pid, section="Method", page=2, char_start=i * 100, char_end=i * 100 + len(t), kind=ChunkKind.BODY, text=t, token_count=len(t.split()))
            for i, (cid, t) in enumerate(chunks)
        ],
    )
    return pid


@pytest.fixture()
def workspace(db: Session) -> ResearchWorkspace:
    p1 = _paper(db, "A", [("a0", "We use dense retrieval on the NQ dataset and report 65.2 exact match.")])
    p2 = _paper(db, "B", [("b0", "We use BM25 sparse retrieval. Results are reported as recall at 20.")])
    return ResearchWorkspace(
        workspace_id="ws_1", owner_id="usr_1", title="W", seed_paper_id=p1, seed_profile_id="prof",
        papers=[
            WorkspacePaper(workspace_id="ws_1", paper_id=p1, added_by=AddedBy.MANUAL, role=WorkspacePaperRole.SEED, grounding=Grounding.FULL_TEXT),
            WorkspacePaper(workspace_id="ws_1", paper_id=p2, added_by=AddedBy.TRAIL, grounding=Grounding.ABSTRACT),
        ],
    )


def _index(db: Session, ws: ResearchWorkspace, settings: Settings) -> FaissWorkspaceIndex:
    idx = FaissWorkspaceIndex(db, workspace_id=ws.workspace_id, index_dir=settings.data_dir / "wi")
    idx.rebuild([p.paper_id for p in ws.papers])
    return idx


def _session(cells_by_paper: dict[str, object]) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        payload: object = {"cells": []}
        for pid, cells in cells_by_paper.items():
            if f"PAPER: {pid}" in body:
                payload = cells
                break
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 9, "completion_tokens": 6}})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="m", provider=LlmProvider.GROQ,
    )


def _run(db, ws, settings, session, *, paper_ids=None, columns=("method", "dataset", "result")):
    return asyncio.run(
        build_comparison(
            db, workspace=ws, comparison_id="cmp_1",
            paper_ids=paper_ids or [p.paper_id for p in ws.papers],
            column_schema=ComparisonSchema(columns=list(columns)),
            session=session, settings=settings, index=_index(db, ws, settings),
        )
    )


def test_grounded_cells_carry_span_claim_and_grounding_flag(db, workspace, settings) -> None:
    ws = workspace
    p1, p2 = ws.papers[0].paper_id, ws.papers[1].paper_id
    res = _run(db, ws, settings, _session({
        p1: {"cells": [
            {"column": "method", "value": "dense retrieval", "chunk_id": "a0", "quote": "We use dense retrieval on the NQ dataset"},
            {"column": "dataset", "value": "NQ", "chunk_id": "a0", "quote": "on the NQ dataset"},
        ]},
        p2: {"cells": [
            {"column": "method", "value": "BM25 sparse retrieval", "chunk_id": "b0", "quote": "We use BM25 sparse retrieval."},
        ]},
    }))
    r1 = next(r for r in res.comparison.rows if r.paper_id == p1)
    assert r1.cells["method"].text == "dense retrieval"
    assert r1.cells["method"].span is not None and r1.cells["method"].span.page == 2
    assert r1.cells["method"].claim_id == "clm_cmp_1_0_method"
    assert r1.cells["method"].grounding == "full_text"
    assert r1.cells["result"].text is None  # not proposed -> missing

    r2 = next(r for r in res.comparison.rows if r.paper_id == p2)
    assert r2.cells["method"].text == "BM25 sparse retrieval"
    assert r2.cells["method"].grounding == "abstract"  # WorkspacePaper.grounding

    # 3 grounded cells / (2 papers * 3 cols) = 0.5
    assert res.comparison.coverage == 0.5
    assert {c.claim_id for c in res.claims} == {"clm_cmp_1_0_method", "clm_cmp_1_0_dataset", "clm_cmp_1_1_method"}
    assert all(c.supporting_chunk_ids and c.is_supported for c in res.claims)


def test_value_with_a_non_verbatim_quote_is_rejected_as_missing(db, workspace, settings) -> None:
    ws = workspace
    p1 = ws.papers[0].paper_id
    res = _run(db, ws, settings, _session({
        p1: {"cells": [{"column": "method", "value": "graph retrieval", "chunk_id": "a0", "quote": "the authors used a graph method"}]},
    }), paper_ids=[p1])
    cell = res.comparison.rows[0].cells["method"]
    assert cell.text is None and cell.span is None and cell.claim_id is None
    assert res.claims == []
    assert res.comparison.coverage == 0.0


def test_value_citing_an_unretrieved_chunk_is_rejected(db, workspace, settings) -> None:
    ws = workspace
    p1 = ws.papers[0].paper_id
    res = _run(db, ws, settings, _session({
        p1: {"cells": [{"column": "method", "value": "dense retrieval", "chunk_id": "chunk_from_another_paper", "quote": "We use dense retrieval on the NQ dataset"}]},
    }), paper_ids=[p1])
    assert res.comparison.rows[0].cells["method"].text is None
    assert res.claims == []


def test_null_value_stays_missing_and_is_never_invented(db, workspace, settings) -> None:
    ws = workspace
    p1 = ws.papers[0].paper_id
    res = _run(db, ws, settings, _session({
        p1: {"cells": [{"column": "dataset", "value": None, "chunk_id": None, "quote": None}]},
    }), paper_ids=[p1])
    assert res.comparison.rows[0].cells["dataset"].text is None
    assert res.claims == []


def test_conflicting_alternates_that_verify_are_recorded(db, workspace, settings) -> None:
    ws = workspace
    p1 = ws.papers[0].paper_id
    res = _run(db, ws, settings, _session({
        p1: {"cells": [{
            "column": "result", "value": "65.2 exact match", "chunk_id": "a0",
            "quote": "report 65.2 exact match", "alternates": ["exact match", "not-in-the-chunk-value"],
        }]},
    }), paper_ids=[p1], columns=("result",))
    cell = res.comparison.rows[0].cells["result"]
    assert cell.text == "65.2 exact match"
    assert cell.conflicting == ["exact match"]  # verified alternate kept; unverified dropped


def test_llm_cannot_introduce_a_column_outside_the_schema(db, workspace, settings) -> None:
    ws = workspace
    p1 = ws.papers[0].paper_id
    res = _run(db, ws, settings, _session({
        p1: {"cells": [
            {"column": "method", "value": "dense retrieval", "chunk_id": "a0", "quote": "We use dense retrieval on the NQ dataset"},
            {"column": "secret_backdoor", "value": "x", "chunk_id": "a0", "quote": "We use dense retrieval"},
        ]},
    }), paper_ids=[p1], columns=("method", "dataset"))
    assert set(res.comparison.rows[0].cells) == {"method", "dataset"}


def test_no_session_yields_all_missing_cells(db, workspace, settings) -> None:
    res = _run(db, workspace, settings, None)
    assert all(cell.text is None for row in res.comparison.rows for cell in row.cells.values())
    assert res.comparison.coverage == 0.0
    assert "comparison_unavailable_no_session" in res.warnings
    assert res.claims == []


def test_llm_failure_for_one_paper_leaves_only_that_paper_missing(db, workspace, settings) -> None:
    ws = workspace
    p1, p2 = ws.papers[0].paper_id, ws.papers[1].paper_id
    res = _run(db, ws, settings, _session({
        p1: {"cells": [{"column": "method", "value": "dense retrieval", "chunk_id": "a0", "quote": "We use dense retrieval on the NQ dataset"}]},
        p2: "not valid json",
    }))
    assert next(r for r in res.comparison.rows if r.paper_id == p1).cells["method"].text == "dense retrieval"
    assert all(c.text is None for c in next(r for r in res.comparison.rows if r.paper_id == p2).cells.values())
    assert any(w.startswith("cell_extraction_failed:") for w in res.warnings)


def test_build_is_deterministic(db, workspace, settings) -> None:
    ws = workspace
    p1 = ws.papers[0].paper_id
    payload: dict[str, object] = {p1: {"cells": [{"column": "method", "value": "dense retrieval", "chunk_id": "a0", "quote": "We use dense retrieval on the NQ dataset"}]}}
    a = _run(db, ws, settings, _session(payload), paper_ids=[p1])
    b = _run(db, ws, settings, _session(payload), paper_ids=[p1])
    assert a.comparison.model_dump(exclude={"created_at"}) == b.comparison.model_dump(exclude={"created_at"})
    assert [c.model_dump() for c in a.claims] == [c.model_dump() for c in b.claims]
