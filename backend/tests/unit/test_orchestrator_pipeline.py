from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db import repository as repo
from app.db.base import Base
from app.domain.orchestrator import StageName
from app.domain.user import ApiKeyStatus, LlmProvider
from app.external.http import ExternalHttpClient
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.security.key_vault import KeyVault
from app.services.discovery.pipeline import DiscoveryOptions
from app.services.orchestrator.orchestrator import InvalidStageInput, ResearchOrchestrator

_VALID_EXTRACTION_JSON = json.dumps(
    {
        "domain": {"value": "NLP", "quote": "We propose RAG."},
        "subdomains": {"items": []},
        "research_problem": {"value": "knowledge intensive question answering", "quote": "We propose RAG."},
        "research_questions": {"items": []},
        "objectives": {"items": []},
        "keywords": ["retrieval augmented generation"],
        "methods": {"items": []},
        "models": {"items": []},
        "algorithms": {"items": []},
        "datasets": {"items": []},
        "evaluation_metrics": {"items": []},
        "findings": {"items": []},
        "limitations": {"items": []},
        "future_work": {"items": []},
        "important_entities": {"items": []},
        "cited_methods": {"items": []},
        "candidate_search_queries": ["retrieval augmented generation"],
    }
)

_ARXIV = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/2005.11401v1</id><published>2020-05-01T00:00:00Z</published>
    <title>Dense Passage Retrieval for Open-Domain QA</title><summary>we introduce DPR</summary>
    <author><name>V. Karpukhin</name></author></entry>
</feed>"""

_OPENALEX_SEARCH = {
    "results": [
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.1/fid",
            "title": "FiD: Fusion-in-Decoder",
            "publication_year": 2021,
            "authorships": [{"author": {"display_name": "G. Izacard"}}],
            "abstract_inverted_index": {"fusion": [0], "in": [1], "decoder": [2]},
        }
    ]
}


async def _no_sleep(_s: float) -> None:
    return None


def _handler(*, empty: bool = False) -> httpx.MockTransport:
    def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "arxiv.org" in url:
            return httpx.Response(200, text="<feed xmlns='http://www.w3.org/2005/Atom'></feed>" if empty else _ARXIV)
        if "openalex.org" in url:
            if "/works/" in url:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"results": []} if empty else _OPENALEX_SEARCH)
        if "semanticscholar.org" in url:  # seed resolution / S2 lookups: not on S2
            return httpx.Response(404, json={})
        if "europepmc" in url:
            return httpx.Response(200, json={"resultList": {"result": []}})
        raise AssertionError(url)

    return httpx.MockTransport(h)


def _discovery_options(*, empty: bool = False) -> DiscoveryOptions:
    return DiscoveryOptions(
        http=ExternalHttpClient(transport=_handler(empty=empty), sleep=_no_sleep),
        chunk_embedder=FakeEmbeddingProvider(),
        doc_embedder=FakeEmbeddingProvider(),
        per_strategy_timeout_s=5.0,
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
    return Settings(_env_file=None, data_dir=tmp_path, key_vault_secret=Fernet.generate_key().decode())  # type: ignore[call-arg]


@pytest.fixture()
def owner(db: Session):  # noqa: ANN201
    return repo.create_user(db, user_id="usr_1", email="researcher@example.com")


def _seed_working_key(db: Session, settings: Settings, owner_id: str) -> None:
    vault = KeyVault(settings.key_vault_secret)
    repo.upsert_api_key(
        db, new_key_id="key_1", owner_id=owner_id, provider=LlmProvider.GROQ,
        key_ciphertext=vault.encrypt("sk-real-key"), key_last4="-key",
        status=ApiKeyStatus.WORKING, checked_at=datetime.now(timezone.utc),
    )


def _mock_profile_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm.providers.openai_compat import OpenAiCompatClient
    from app.services.profile import pipeline as profile_pipeline

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": _VALID_EXTRACTION_JSON}}]})

    def fake(provider: object):  # noqa: ANN202
        return OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    monkeypatch.setattr(profile_pipeline, "get_llm_client", fake)


def _orch(db: Session, settings: Settings) -> ResearchOrchestrator:
    return ResearchOrchestrator(db=db, settings=settings)


# --- complete end-to-end orchestration --------------------------------------


def test_full_pipeline_runs_ingest_through_workspace_creation(
    db: Session, settings: Settings, owner, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_working_key(db, settings, owner.id)
    _mock_profile_llm(monkeypatch)
    orch = _orch(db, settings)

    result = asyncio.run(
        orch.run_full_pipeline(
            owner=owner, pdf_bytes=normal_paper_pdf_bytes, filename="paper.pdf",
            workspace_title="My Survey", discovery_options=_discovery_options(),
        )
    )

    assert result.error is None
    assert result.failed_stage is None
    assert result.workspace is not None
    assert result.workspace.seed_paper_id == result.paper_id
    assert result.run_id is not None

    ws = repo.get_workspace(db, result.workspace.workspace_id, owner.id)
    assert ws is not None
    assert ws.seed_paper_id == result.paper_id

    # pre-workspace stage_runs (including "workspace" itself, recorded
    # before the row exists) carry workspace_id=None by design -- the
    # per-workspace activity feed only ever shows post-workspace stages.
    from app.db.models import StageRunORM

    all_stages = [r.stage for r in db.query(StageRunORM).all()]
    assert "workspace" in all_stages
    assert repo.list_stage_runs(db, result.workspace.workspace_id) == []


def test_full_pipeline_writes_a_stage_run_for_every_pre_workspace_stage(
    db: Session, settings: Settings, owner, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_working_key(db, settings, owner.id)
    _mock_profile_llm(monkeypatch)
    orch = _orch(db, settings)

    asyncio.run(
        orch.run_full_pipeline(
            owner=owner, pdf_bytes=normal_paper_pdf_bytes, filename="paper.pdf",
            workspace_title="My Survey", discovery_options=_discovery_options(),
        )
    )

    from app.db.models import StageRunORM

    rows = db.query(StageRunORM).order_by(StageRunORM.ts).all()
    stages_seen = [r.stage for r in rows]
    for expected in ("ingest", "profile", "discovery", "ranking", "trail", "workspace"):
        assert expected in stages_seen, f"missing stage_runs row for {expected}"
    assert all(r.ok for r in rows), [r.error for r in rows if not r.ok]


# --- partial upstream failure / bounded extra citation hop ------------------


def test_thin_discovery_triggers_exactly_one_extra_citation_hop(
    db: Session, settings: Settings, owner, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_working_key(db, settings, owner.id)
    _mock_profile_llm(monkeypatch)
    settings.orchestrator_min_candidates_for_hop = 1000  # force the boundary to trigger
    orch = _orch(db, settings)

    result = asyncio.run(
        orch.run_full_pipeline(
            owner=owner, pdf_bytes=normal_paper_pdf_bytes, filename="paper.pdf",
            workspace_title="My Survey", discovery_options=_discovery_options(),
        )
    )

    assert result.extra_citation_hop_used is True
    assert result.run_id is not None
    run = repo.get_search_run(db, result.run_id)
    assert run is not None and run.extra_citation_hop_used is True

    from app.db.models import StageRunORM

    discovery_rows = db.query(StageRunORM).filter_by(stage="discovery").all()
    assert len(discovery_rows) == 2  # the original pass + exactly one extra hop


def test_a_healthy_discovery_never_authorises_an_extra_hop(
    db: Session, settings: Settings, owner, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_working_key(db, settings, owner.id)
    _mock_profile_llm(monkeypatch)
    settings.orchestrator_min_candidates_for_hop = 0
    settings.orchestrator_min_strategy_diversity = 0
    orch = _orch(db, settings)

    result = asyncio.run(
        orch.run_full_pipeline(
            owner=owner, pdf_bytes=normal_paper_pdf_bytes, filename="paper.pdf",
            workspace_title="My Survey", discovery_options=_discovery_options(),
        )
    )

    assert result.extra_citation_hop_used is False
    from app.db.models import StageRunORM

    assert db.query(StageRunORM).filter_by(stage="discovery").count() == 1


# --- stage failure / recovery + invalid stage inputs ------------------------


def test_a_paper_with_no_full_text_cannot_be_profiled(db: Session) -> None:
    from app.db.models import PaperORM

    bare = PaperORM(id="pap_bare", title="Bare", title_hash="h", has_full_text=False)
    with pytest.raises(InvalidStageInput):
        ResearchOrchestrator._require_profileable(bare, "pap_bare")


def test_a_missing_paper_is_also_an_invalid_stage_input() -> None:
    with pytest.raises(InvalidStageInput):
        ResearchOrchestrator._require_profileable(None, "pap_ghost")


def test_a_paper_with_full_text_passes_the_precondition() -> None:
    from app.db.models import PaperORM

    ready = PaperORM(id="pap_ready", title="Ready", title_hash="h", has_full_text=True)
    ResearchOrchestrator._require_profileable(ready, "pap_ready")  # does not raise


def test_no_working_llm_key_fails_the_profile_stage_and_stops(
    db: Session, settings: Settings, owner, normal_paper_pdf_bytes: bytes
) -> None:
    orch = _orch(db, settings)

    result = asyncio.run(
        orch.run_full_pipeline(
            owner=owner, pdf_bytes=normal_paper_pdf_bytes, filename="paper.pdf",
            workspace_title="W", discovery_options=_discovery_options(),
        )
    )

    assert result.failed_stage == StageName.PROFILE
    assert result.workspace is None
    from app.db.models import StageRunORM

    profile_rows = db.query(StageRunORM).filter_by(stage="profile").all()
    assert profile_rows and all(not r.ok for r in profile_rows)


# --- job / status tracking ---------------------------------------------------


def test_job_progress_is_tracked_across_the_full_pipeline(
    db: Session, settings: Settings, owner, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.domain.jobs import Job, JobKind, JobStatus

    _seed_working_key(db, settings, owner.id)
    _mock_profile_llm(monkeypatch)
    job = repo.create_job(db, Job(job_id="job_1", owner_id=owner.id, workspace_id=None, kind=JobKind.PIPELINE))
    orch = _orch(db, settings)

    result = asyncio.run(
        orch.run_full_pipeline(
            owner=owner, pdf_bytes=normal_paper_pdf_bytes, filename="paper.pdf",
            workspace_title="W", discovery_options=_discovery_options(), job_id=job.job_id,
        )
    )

    updated = repo.get_job(db, "job_1")
    assert updated is not None
    assert updated.status == JobStatus.SUCCEEDED
    assert result.workspace is not None
    assert updated.result_ref == result.workspace.workspace_id


def test_job_is_marked_failed_when_a_required_stage_fails(
    db: Session, settings: Settings, owner, normal_paper_pdf_bytes: bytes
) -> None:
    from app.domain.jobs import Job, JobKind, JobStatus

    job = repo.create_job(db, Job(job_id="job_2", owner_id=owner.id, workspace_id=None, kind=JobKind.PIPELINE))
    orch = _orch(db, settings)

    asyncio.run(
        orch.run_full_pipeline(
            owner=owner, pdf_bytes=normal_paper_pdf_bytes, filename="paper.pdf",
            workspace_title="W", discovery_options=_discovery_options(), job_id=job.job_id,
        )
    )

    updated = repo.get_job(db, "job_2")
    assert updated is not None and updated.status == JobStatus.FAILED


# --- tenant isolation --------------------------------------------------------


def test_run_stage_does_not_swallow_a_tenant_isolation_error(db: Session, settings: Settings, owner) -> None:  # noqa: ANN001
    from app.services.workspace import pipeline as workspace_pipeline

    orch = _orch(db, settings)

    async def go() -> None:
        await orch.run_stage(
            StageName.GAPS, "get_workspace",
            orch.sync_call(lambda: workspace_pipeline.get_workspace(db, owner=owner, workspace_id="ws_ghost")),
            owner_id=owner.id,
        )

    with pytest.raises(workspace_pipeline.WorkspaceNotFound):
        asyncio.run(go())


# --- deterministic reruns -----------------------------------------------------


def test_reingesting_identical_bytes_is_idempotent(
    db: Session, settings: Settings, owner, normal_paper_pdf_bytes: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_working_key(db, settings, owner.id)
    _mock_profile_llm(monkeypatch)
    orch = _orch(db, settings)

    r1 = asyncio.run(
        orch.run_full_pipeline(
            owner=owner, pdf_bytes=normal_paper_pdf_bytes, filename="paper.pdf",
            workspace_title="W1", discovery_options=_discovery_options(),
        )
    )
    r2 = asyncio.run(
        orch.run_full_pipeline(
            owner=owner, pdf_bytes=normal_paper_pdf_bytes, filename="paper-again.pdf",
            workspace_title="W2", discovery_options=_discovery_options(),
        )
    )

    # the underlying ingest is content-hash idempotent -- the SAME paper row
    # is reused both times, even though each orchestrator run mints its own
    # new workspace (a fresh container is the expected, documented behaviour).
    assert r1.paper_id == r2.paper_id
