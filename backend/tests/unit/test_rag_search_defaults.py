"""What chat and comparison search a workspace with (remediation Phase 11):
a real embedder in production, the lexical index when it can't load, and
the retrieval order when no cross-encoder is installed -- never the test
stand-ins outside tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.rag import RetrievedChunk
from app.retrieval.reranker import FakeCrossEncoder, get_reranker
from app.retrieval.workspace_index import (
    DbBackedWorkspaceIndex,
    FaissWorkspaceIndex,
    workspace_search_index,
)
from app.services.rag.rerank import rerank


def test_production_searches_with_the_real_embedder_and_no_stand_in_reranker(monkeypatch: pytest.MonkeyPatch) -> None:
    # tests/conftest.py pins the stand-ins for the suite; production is what's left without it
    monkeypatch.delenv("RESEARCHNEXUS_RAG_EMBEDDER", raising=False)
    monkeypatch.delenv("RESEARCHNEXUS_RAG_RERANKER", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.rag_embedder == "fastembed"
    assert settings.rag_reranker == "none"


def test_without_a_cross_encoder_the_retrieval_order_stands() -> None:
    chunks = [
        RetrievedChunk(chunk_id=f"c{i}", paper_id="p", text=t, score=s)
        for i, (t, s) in enumerate([("face recognition with CNNs", 0.9), ("attendance", 0.8), ("a face", 0.7)])
    ]
    kept = rerank("attendance face", chunks, get_reranker("none"), top_n=2)
    assert [c.chunk_id for c in kept] == ["c0", "c1"]
    # the token-overlap stand-in would have reordered them by shared words
    assert [c.chunk_id for c in rerank("attendance face", chunks, FakeCrossEncoder(), top_n=3)][0] != "c0"


def test_search_falls_back_to_the_lexical_index_when_no_embedder_loads(tmp_path: Path) -> None:
    db = Session()  # never queried: constructing an index does no I/O
    lexical = workspace_search_index(db, workspace_id="ws", settings=Settings(_env_file=None, data_dir=tmp_path, rag_embedder="none"))  # type: ignore[call-arg]
    assert isinstance(lexical, DbBackedWorkspaceIndex)
    semantic = workspace_search_index(db, workspace_id="ws", settings=Settings(_env_file=None, data_dir=tmp_path, rag_embedder="fake"))  # type: ignore[call-arg]
    assert isinstance(semantic, FaissWorkspaceIndex)
