"""Ranking criteria through the API (remediation Phase 9): set before
discovery and applied by the real ranking stage, re-weighed on a saved run,
validated, and reported with the results."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.models import PaperORM
from app.db.session import get_session_factory
from app.domain.candidate import (
    CitationRelationship,
    DiscoveryStrategy,
    NormalizedCandidate,
    SearchRun,
)
from app.domain.profile import ProfileField, ResearchProfile
from app.main import create_app
from app.retrieval.embeddings import FakeEmbeddingProvider
from app.services.normalize.canonical import title_hash
from app.services.ranking.pipeline import RankOptions, rank_search_run
from tests.integration.test_discover_related_api import _fake_build_trail, _fake_run_discovery


def _client(tmp_path: Path) -> tuple[TestClient, Settings]:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
        key_vault_secret=Fernet.generate_key().decode(),
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app), settings


def _headers(c: TestClient) -> dict[str, str]:
    token = c.post("/api/v1/auth/session", json={"email": "r@example.com", "password": "x"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _seed() -> None:
    db = get_session_factory()()
    try:
        repo.save_paper(db, PaperORM(id="pap_seed", title="Seed Paper", title_hash=title_hash("pap_seed"), has_full_text=True, abstract="retrieval"))
        repo.upsert_profile(
            db,
            ResearchProfile(
                profile_id="prof_seed", paper_id="pap_seed", title="Seed Paper", abstract="retrieval",
                domain=ProfileField(value="IR"), research_problem=ProfileField(value="dense retrieval"),
            ),
        )
    finally:
        db.close()


def _ranked_run(settings: Settings) -> str:
    """A real saved ranking: three candidates ranked by the real pipeline."""
    db = get_session_factory()()
    try:
        repo.create_search_run(db, SearchRun(run_id="run_1", seed_paper_id="pap_seed", strategies_succeeded=[DiscoveryStrategy.KEYWORD]))
        specs = [
            ("Old retrieval paper", "dense retrieval for question answering", 2004, CitationRelationship.NONE),
            ("Brand new paper", "a database survey", 2025, CitationRelationship.NONE),
            ("Paper the seed cites", "passage ranking", 2012, CitationRelationship.CITED_BY_SEED),
        ]
        for i, (title, abstract, year, rel) in enumerate(specs, start=1):
            pid = repo.upsert_discovered_paper(db, NormalizedCandidate(title=title, title_hash=title_hash(title), abstract=abstract, year=year))
            repo.add_search_candidate(
                db, candidate_id=f"cand_1_{i:04d}", run_id="run_1", paper_id=pid,
                discovery_methods=[DiscoveryStrategy.KEYWORD], possible_duplicate_of=None, provenance={},
                citation_relationship=rel, citation_hops=1 if rel is not CitationRelationship.NONE else None,
            )
        options = RankOptions(chunk_embedder=FakeEmbeddingProvider(), doc_embedder=FakeEmbeddingProvider())
        asyncio.run(rank_search_run(db, run_id="run_1", settings=settings, options=options))
    finally:
        db.close()
    return "run_1"


def _titles(body: dict) -> list[str]:
    return [r["paper"]["title"] for r in body["results"]]


def test_criteria_set_before_discovery_rank_the_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def capturing_rank(db, *, run_id, settings, options):  # noqa: ANN001
        seen["weights"] = options.weights
        return await rank_search_run(db, run_id=run_id, settings=settings, options=RankOptions(weights=options.weights))

    monkeypatch.setattr("app.services.discovery.pipeline.run_discovery", _fake_run_discovery)
    monkeypatch.setattr("app.services.ranking.pipeline.rank_search_run", capturing_rank)
    monkeypatch.setattr("app.services.trail.pipeline.build_trail", _fake_build_trail)
    c, _ = _client(tmp_path)
    headers = _headers(c)
    _seed()
    criteria = {"topic": 10, "problem": 0, "methods": 0, "datasets": 0, "citations": 0, "recency": 90, "publisher": 0}
    started = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers, json={"criteria": criteria}).json()
    job = c.get(started["job"]["poll_url"]).json()
    assert job["status"] == "succeeded"
    assert job["progress"]["ranking_criteria"] == criteria
    assert seen["weights"].version == "c-10.0.0.0.0.90.0"  # type: ignore[attr-defined]
    related = c.get(f"/api/v1/papers/pap_seed/related?run_id={job['result_ref']}", headers=headers).json()
    assert related["run"]["ranking_criteria"] == criteria
    assert related["results"][0]["weights_version"] == "c-10.0.0.0.0.90.0"


def test_starting_discovery_without_criteria_uses_the_default_criteria(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.discovery.pipeline.run_discovery", _fake_run_discovery)
    monkeypatch.setattr("app.services.trail.pipeline.build_trail", _fake_build_trail)
    c, _ = _client(tmp_path)
    headers = _headers(c)
    _seed()
    job = c.get(c.post("/api/v1/papers/pap_seed/discover-related", headers=headers).json()["job"]["poll_url"]).json()
    # the initial weights, plus the preferred-publisher criterion the reader chose (2026-10-02)
    assert job["progress"]["ranking_criteria"] == {
        "topic": 42, "problem": 18, "methods": 14, "datasets": 8, "citations": 12, "recency": 6, "publisher": 15,
    }


@pytest.mark.parametrize(
    "criteria",
    [
        {"topic": 0, "problem": 0, "methods": 0, "datasets": 0, "citations": 0, "recency": 0, "publisher": 0},
        {"topic": 150},
        {"topic": -5},
        {"novelty": 10},
    ],
)
def test_invalid_criteria_are_refused_before_anything_runs(tmp_path: Path, criteria: dict[str, int]) -> None:
    c, _ = _client(tmp_path)
    headers = _headers(c)
    _seed()
    resp = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers, json={"criteria": criteria})
    assert resp.status_code == 422


def test_a_saved_ranking_is_reweighed_and_returned(tmp_path: Path) -> None:
    c, settings = _client(tmp_path)
    headers = _headers(c)
    _seed()
    run_id = _ranked_run(settings)

    newest = c.post(
        "/api/v1/papers/pap_seed/related/rerank", headers=headers,
        json={"run_id": run_id, "criteria": {"topic": 0, "problem": 0, "methods": 0, "datasets": 0, "citations": 0, "recency": 100}},
    )
    assert newest.status_code == 200, newest.text
    assert _titles(newest.json())[0] == "Brand new paper"
    assert newest.json()["run"]["ranking_criteria"]["recency"] == 100
    top = newest.json()["results"][0]["explanation"]
    assert top["contributions"][0]["signal"] == "recency"

    cited = c.post(
        "/api/v1/papers/pap_seed/related/rerank", headers=headers,
        json={"run_id": run_id, "criteria": {"topic": 0, "problem": 0, "methods": 0, "datasets": 0, "citations": 100, "recency": 0}},
    ).json()
    assert _titles(cited)[0] == "Paper the seed cites"
    # the saved order is the new one
    again = c.get(f"/api/v1/papers/pap_seed/related?run_id={run_id}", headers=headers).json()
    assert _titles(again) == _titles(cited)


def test_reweighing_refuses_another_papers_run_an_unranked_run_and_bad_criteria(tmp_path: Path) -> None:
    c, settings = _client(tmp_path)
    headers = _headers(c)
    _seed()
    run_id = _ranked_run(settings)
    good = {"topic": 1, "problem": 1, "methods": 1, "datasets": 1, "citations": 1, "recency": 1}
    assert c.post("/api/v1/papers/pap_other/related/rerank", headers=headers, json={"run_id": run_id, "criteria": good}).status_code == 404
    db = get_session_factory()()
    try:
        repo.create_search_run(db, SearchRun(run_id="run_unranked", seed_paper_id="pap_seed"))
    finally:
        db.close()
    assert c.post("/api/v1/papers/pap_seed/related/rerank", headers=headers, json={"run_id": "run_unranked", "criteria": good}).status_code == 409
    bad = {**good, "topic": 101}
    assert c.post("/api/v1/papers/pap_seed/related/rerank", headers=headers, json={"run_id": run_id, "criteria": bad}).status_code == 422
    assert c.post("/api/v1/papers/pap_seed/related/rerank", json={"run_id": run_id, "criteria": good}).status_code == 401


def _set_publishers(by_title: dict[str, str]) -> None:
    db = get_session_factory()()
    try:
        for paper in db.query(PaperORM).filter(PaperORM.title.in_(list(by_title))):
            paper.publisher = by_title[paper.title]
        db.commit()
    finally:
        db.close()


def test_the_reader_chooses_which_publishers_are_preferred(tmp_path: Path) -> None:
    # remediation 2026-10-06: the preferred publishers are the reader's to choose, not a fixed four
    c, settings = _client(tmp_path)
    headers = _headers(c)
    _seed()
    run_id = _ranked_run(settings)
    _set_publishers({"Old retrieval paper": "MDPI", "Brand new paper": "IEEE", "Paper the seed cites": "Wiley"})
    only_publisher = {"topic": 0, "problem": 0, "methods": 0, "datasets": 0, "citations": 0, "recency": 0, "publisher": 100}

    def rerank(**extra: object) -> dict:
        resp = c.post("/api/v1/papers/pap_seed/related/rerank", headers=headers, json={"run_id": run_id, "criteria": only_publisher, **extra})
        assert resp.status_code == 200, resp.text
        return resp.json()

    def signal(body: dict, title: str) -> float:
        [row] = [r for r in body["results"] if r["paper"]["title"] == title]
        return row["signals"]["publisher"]

    default = rerank()
    assert _titles(default)[0] == "Brand new paper"  # IEEE, one of the default four
    assert default["run"]["preferred_publishers"] == ["IEEE", "Springer", "ACM", "Elsevier"]

    chosen = rerank(preferred_publishers=["mdpi", "  Wiley ", "MDPI"])
    assert chosen["run"]["preferred_publishers"] == ["MDPI", "Wiley"]  # named as readers know them, once each
    assert signal(chosen, "Old retrieval paper") == 1.0 and signal(chosen, "Paper the seed cites") == 1.0
    assert signal(chosen, "Brand new paper") == 0.0
    assert _titles(chosen)[-1] == "Brand new paper"
    # the run remembers what it was ranked with
    assert c.get(f"/api/v1/papers/pap_seed/related?run_id={run_id}", headers=headers).json()["run"]["preferred_publishers"] == ["MDPI", "Wiley"]

    none = rerank(preferred_publishers=[])
    assert none["run"]["preferred_publishers"] == []
    assert {signal(none, t) for t in _titles(none)} == {0.0}

    for bad in ([f"Publisher {i}" for i in range(31)], ["   "], ["x" * 121]):
        resp = c.post("/api/v1/papers/pap_seed/related/rerank", headers=headers, json={"run_id": run_id, "criteria": only_publisher, "preferred_publishers": bad})
        assert resp.status_code == 422, bad


def test_discovery_ranks_with_the_readers_preferred_publishers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def capturing_rank(db, *, run_id, settings, options):  # noqa: ANN001
        seen["preferred"] = options.preferred_publishers
        return await rank_search_run(db, run_id=run_id, settings=settings, options=RankOptions(weights=options.weights))

    monkeypatch.setattr("app.services.discovery.pipeline.run_discovery", _fake_run_discovery)
    monkeypatch.setattr("app.services.ranking.pipeline.rank_search_run", capturing_rank)
    monkeypatch.setattr("app.services.trail.pipeline.build_trail", _fake_build_trail)
    c, _ = _client(tmp_path)
    headers = _headers(c)
    _seed()
    started = c.post("/api/v1/papers/pap_seed/discover-related", headers=headers, json={"preferred_publishers": ["acm", "IET"]}).json()
    job = c.get(started["job"]["poll_url"]).json()
    assert job["status"] == "succeeded"
    assert seen["preferred"] == ("ACM", "IET")
    assert job["progress"]["preferred_publishers"] == ["ACM", "IET"]
