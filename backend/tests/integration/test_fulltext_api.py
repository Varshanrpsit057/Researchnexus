"""Full text through the real API (remediation Phase 7): every paper says
what text it is read from; asking for a paper's full text gets it from a
legitimate source; papers joining a workspace are looked for in the
background, and the workspace reads them from full text from then on."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.models import PaperORM
from app.db.session import get_session_factory
from app.external.http import ExternalHttpClient
from app.main import create_app
from app.services.normalize.canonical import title_hash
from tests.integration.test_workspaces_api import _headers, _seed_analysed_paper, _token


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        jwt_secret="test-jwt-secret",
        **overrides,  # type: ignore[arg-type]
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(app)


def _sources(monkeypatch: pytest.MonkeyPatch, pdf: bytes, seen: list[str]) -> None:
    """The open-access sources, answered here: arXiv serves one paper's PDF;
    OpenAlex and Semantic Scholar know of no copy of anything else."""

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "arxiv.org":
            return httpx.Response(200, content=pdf)
        if request.url.host == "api.openalex.org":
            return httpx.Response(200, json={"id": "https://openalex.org/W1", "ids": {}, "locations": []})
        return httpx.Response(404)

    def fake(_settings: Settings) -> ExternalHttpClient:
        return ExternalHttpClient(transport=httpx.MockTransport(handler))

    import app.services.fulltext.batch as batch
    import app.services.fulltext.retrieve as retrieve

    monkeypatch.setattr(retrieve, "fulltext_http", fake)
    monkeypatch.setattr(batch, "fulltext_http", fake)


def _found(pid: str, **kw: object) -> None:
    db = get_session_factory()()
    try:
        fields: dict = {"id": pid, "title": f"Found {pid}", "title_hash": title_hash(pid), "source": "discovery", "abstract": "An abstract."}
        repo.save_paper(db, PaperORM(**(fields | kw)))
    finally:
        db.close()


def test_a_paper_says_what_text_it_has_and_gets_its_full_text_on_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, normal_paper_pdf_bytes: bytes
) -> None:
    client = _client(tmp_path)
    token = _token(client)
    _found("pap_arxiv", arxiv_id="2005.11401")
    seen: list[str] = []
    _sources(monkeypatch, normal_paper_pdf_bytes, seen)

    before = client.get("/api/v1/papers/pap_arxiv").json()["coverage"]
    assert (before["state"], before["status"], before["retrievable"]) == ("abstract_only", None, True)

    resp = client.post("/api/v1/papers/pap_arxiv/fulltext", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["outcome"]["status"], body["outcome"]["source"]) == ("retrieved", "arxiv")
    assert body["coverage"]["state"] == "full_text"
    paper = client.get("/api/v1/papers/pap_arxiv").json()
    assert paper["has_full_text"] is True and paper["sections"] and paper["coverage"]["source"] == "arxiv"

    assert client.post("/api/v1/papers/pap_arxiv/fulltext").status_code == 401
    assert client.post("/api/v1/papers/pap_missing/fulltext", headers=_headers(token)).status_code == 404


def test_papers_joining_a_workspace_are_looked_for_and_read_from_full_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, normal_paper_pdf_bytes: bytes
) -> None:
    client = _client(tmp_path, fulltext_auto=True)
    token = _token(client)
    _seed_analysed_paper()
    _found("pap_arxiv", arxiv_id="2005.11401")
    _found("pap_closed", doi="10.1/closed")
    _found("pap_bare", abstract=None)
    seen: list[str] = []
    _sources(monkeypatch, normal_paper_pdf_bytes, seen)
    wid = client.post("/api/v1/workspaces", json={"title": "W", "seed_paper_id": "pap_seed"}, headers=_headers(token)).json()["workspace_id"]

    added = client.post(
        f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": ["pap_arxiv", "pap_closed", "pap_bare"]}, headers=_headers(token)
    ).json()
    assert added["fulltext_job"]["kind"] == "fulltext"

    coverage = client.get(f"/api/v1/workspaces/{wid}/coverage", headers=_headers(token)).json()
    states = {p["paper_id"]: p["coverage"]["state"] for p in coverage["papers"]}
    assert states == {"pap_seed": "full_text", "pap_arxiv": "full_text", "pap_closed": "abstract_only", "pap_bare": "no_text"}
    assert coverage["summary"] == {"full_text": 2, "abstract_only": 1, "retrieval_failed": 0, "no_text": 1}
    assert coverage["job"]["status"] == "succeeded" and coverage["job"]["progress"]["retrieved"] == "1"
    reasons = {p["paper_id"]: p["coverage"]["reason"] for p in coverage["papers"]}
    assert (reasons["pap_closed"], reasons["pap_bare"]) == ("no_open_access_copy", "no_identifier")

    # the workspace reads the retrieved paper from its full text now
    members = client.get(f"/api/v1/workspaces/{wid}", headers=_headers(token)).json()["papers"]
    assert {p["paper_id"]: p["grounding"] for p in members}["pap_arxiv"] == "full_text"

    # asked again: nothing retrieved twice, and the two without a copy are looked for again
    asked = len(seen)
    again = client.post(f"/api/v1/workspaces/{wid}/fulltext", headers=_headers(token)).json()
    assert again["job"]["kind"] == "fulltext"
    assert not any("arxiv.org" in u for u in seen[asked:])
    assert any("10.1/closed" in u for u in seen[asked:])


def test_a_run_whose_server_stopped_is_reported_over_and_a_new_one_can_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, normal_paper_pdf_bytes: bytes
) -> None:
    from datetime import datetime, timedelta, timezone

    from app.db.models import JobORM

    client = _client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    _found("pap_arxiv", arxiv_id="2005.11401")
    _sources(monkeypatch, normal_paper_pdf_bytes, [])
    wid = client.post("/api/v1/workspaces", json={"title": "W", "seed_paper_id": "pap_seed"}, headers=_headers(token)).json()["workspace_id"]
    client.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": ["pap_arxiv"]}, headers=_headers(token))
    db = get_session_factory()()
    try:
        owner = repo.get_workspace(db, wid, client.get("/api/v1/me", headers=_headers(token)).json()["id"])
        assert owner is not None
        db.add(JobORM(id="job_dead", owner_id=owner.owner_id, workspace_id=wid, kind="fulltext", status="running",
                      progress={"stage": "retrieving"}, updated_at=datetime.now(timezone.utc) - timedelta(hours=1)))
        db.commit()
    finally:
        db.close()

    job = client.get(f"/api/v1/workspaces/{wid}/coverage", headers=_headers(token)).json()["job"]
    assert (job["job_id"], job["status"], job["error"]) == ("job_dead", "failed", "The run was interrupted before it finished.")
    started = client.post(f"/api/v1/workspaces/{wid}/fulltext", headers=_headers(token)).json()["job"]
    assert started["job_id"] != "job_dead"


def test_nothing_is_looked_for_when_every_paper_already_has_its_text(tmp_path: Path) -> None:
    client = _client(tmp_path, fulltext_auto=True)
    token = _token(client)
    _seed_analysed_paper()
    wid = client.post("/api/v1/workspaces", json={"title": "W", "seed_paper_id": "pap_seed"}, headers=_headers(token)).json()["workspace_id"]
    assert client.post(f"/api/v1/workspaces/{wid}/fulltext", headers=_headers(token)).json() == {"job": None}
    assert client.get(f"/api/v1/workspaces/{wid}/coverage", headers=_headers(token)).json()["job"] is None
