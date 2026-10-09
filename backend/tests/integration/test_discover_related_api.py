"""`POST /papers/{id}/discover-related` and `GET /papers/{id}/related`
(Roadmap Phase 15) -- the first HTTP path to the Phase 5/6/7
discovery/ranking/trail pipelines. The three pipeline entrypoints are
monkeypatched at their defining module (picked up by `run_discover_related_
job`'s call-time local imports) so this test exercises the new router +
job + read-model wiring without hitting a real scholarly API or LLM --
`run_discovery`/`rank_search_run`/`build_trail` themselves are already
covered by their own Phase 5/6/7 test suites.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.models import PaperORM
from app.db.session import get_session_factory
from app.domain.candidate import DiscoveryStrategy, NormalizedCandidate, SearchRun
from app.domain.profile import Confidence, ProfileField, ResearchProfile
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.main import create_app
from app.services.discovery.pipeline import DiscoveryResult
from app.services.normalize.canonical import title_hash
from app.services.ranking.pipeline import RankResult
from app.services.trail.pipeline import TrailBuildResult
from tests.auth_helpers import sign_in


def _client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
        key_vault_secret=Fernet.generate_key().decode(),
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _token(c: TestClient, email: str = "r@example.com") -> str:
    return sign_in(c, email)


def _h(t: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {t}"}


def _seed_analyzed_paper(paper_id: str) -> None:
    factory = get_session_factory()
    db = factory()
    try:
        repo.save_paper(db, PaperORM(id=paper_id, title="Seed Paper", title_hash=title_hash(paper_id), has_full_text=True))
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id=f"prof_{paper_id}",
                paper_id=paper_id,
                title="Seed Paper",
                abstract="ab",
                domain=ProfileField(value="IR"),
                research_problem=ProfileField(value="dense retrieval"),
            ),
        )
    finally:
        db.close()


async def _fake_run_discovery(db, *, seed_paper_id, current_user, settings, options):  # noqa: ANN001, ARG001
    run_id = f"run_fake_{seed_paper_id}"
    cand_pid = repo.upsert_discovered_paper(
        db, NormalizedCandidate(title="Related Paper", title_hash=title_hash(f"related-{seed_paper_id}"))
    )
    repo.create_search_run(
        db,
        SearchRun(
            run_id=run_id,
            seed_paper_id=seed_paper_id,
            strategies_succeeded=[DiscoveryStrategy.KEYWORD],
            candidate_count_raw=1,
            candidate_count_after_dedupe=1,
            candidate_count_after_filter=1,
        ),
    )
    repo.add_search_candidate(
        db,
        candidate_id="cand_1",
        run_id=run_id,
        paper_id=cand_pid,
        discovery_methods=[DiscoveryStrategy.KEYWORD],
        possible_duplicate_of=None,
        provenance={},
    )
    return DiscoveryResult(
        run_id=run_id,
        status="succeeded",
        strategies_succeeded=["keyword"],
        strategies_failed=[],
        count_raw=1,
        count_after_dedupe=1,
        count_after_filter=1,
    )


async def _fake_rank_search_run(db, *, run_id, settings, options):  # noqa: ANN001, ARG001
    ids = repo.get_search_candidate_paper_ids(db, run_id)
    ranked = [
        RankedPaper(
            candidate_id="cand_1",
            signals=SignalScores(semantic_doc=0.8),
            weights_version="w0-initial",
            fused_score=0.8,
            rerank_score=0.8,
            final_rank=1,
            band=Confidence.HIGH,
            explanation=RankingExplanation(bullet_reasons=["shares the seed's research problem"], prose="p."),
        )
    ]
    repo.save_ranked_papers(db, run_id, ranked, ids)
    return RankResult(run_id=run_id, weights_version="w0-initial", ranked_count=1, reranked_count=1)


async def _fake_build_trail(db, *, run_id, settings, options):  # noqa: ANN001, ARG001
    return TrailBuildResult(run_id=run_id, edge_count=1, typed_targets=1, unknown_targets=0, contradiction_edges=0)


def _patch_pipelines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.discovery.pipeline.run_discovery", _fake_run_discovery)
    monkeypatch.setattr("app.services.ranking.pipeline.rank_search_run", _fake_rank_search_run)
    monkeypatch.setattr("app.services.trail.pipeline.build_trail", _fake_build_trail)


def test_discover_related_runs_the_job_and_related_returns_ranked_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_pipelines(monkeypatch)
    c = _client(tmp_path)
    token = _token(c)
    _seed_analyzed_paper("pap_seed")

    resp = c.post("/api/v1/papers/pap_seed/discover-related", headers=_h(token))
    assert resp.status_code == 202, resp.text
    job = resp.json()["job"]
    assert job["kind"] == "discover"
    assert job["status"] == "queued"

    job_status = c.get(job["poll_url"], headers=_h(token)).json()
    assert job_status["status"] == "succeeded"
    run_id = job_status["result_ref"]

    related = c.get(f"/api/v1/papers/pap_seed/related?run_id={run_id}", headers=_h(token))
    assert related.status_code == 200, related.text
    body = related.json()
    assert body["run"]["run_id"] == run_id
    assert body["run"]["seed_paper_id"] == "pap_seed"
    assert body["run"]["strategies_succeeded"] == ["keyword"]
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["paper"]["title"] == "Related Paper"
    assert result["final_rank"] == 1
    assert result["band"] == "high"
    assert result["explanation"]["bullet_reasons"] == ["shares the seed's research problem"]


def test_discover_related_404s_for_a_missing_paper(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    resp = c.post("/api/v1/papers/pap_ghost/discover-related", headers=_h(token))
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "not_found"


def test_discover_related_409s_when_paper_has_not_been_analyzed(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    factory = get_session_factory()
    db = factory()
    try:
        repo.save_paper(db, PaperORM(id="pap_raw", title="Raw", title_hash=title_hash("pap_raw"), has_full_text=True))
    finally:
        db.close()

    resp = c.post("/api/v1/papers/pap_raw/discover-related", headers=_h(token))
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["code"] == "conflict"


def test_discover_related_requires_authentication(tmp_path: Path) -> None:
    c = _client(tmp_path)
    _seed_analyzed_paper("pap_seed")
    resp = c.post("/api/v1/papers/pap_seed/discover-related")
    assert resp.status_code == 401


def test_related_404s_for_an_unknown_run(tmp_path: Path) -> None:
    c = _client(tmp_path)
    token = _token(c)
    _seed_analyzed_paper("pap_seed")
    resp = c.get("/api/v1/papers/pap_seed/related?run_id=run_ghost", headers=_h(token))
    assert resp.status_code == 404


def test_related_404s_when_run_belongs_to_a_different_paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_pipelines(monkeypatch)
    c = _client(tmp_path)
    token = _token(c)
    _seed_analyzed_paper("pap_a")
    _seed_analyzed_paper("pap_b")

    resp = c.post("/api/v1/papers/pap_a/discover-related", headers=_h(token))
    run_id = c.get(resp.json()["job"]["poll_url"], headers=_h(token)).json()["result_ref"]

    mismatched = c.get(f"/api/v1/papers/pap_b/related?run_id={run_id}", headers=_h(token))
    assert mismatched.status_code == 404
