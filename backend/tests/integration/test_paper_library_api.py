"""A reader's paper library (remediation, 2026-10-06): every paper they
uploaded, analysed, searched from or collected into a workspace, from the
server -- it used to be a list kept in one browser."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.db.models import ResearchProfileORM, SearchRunORM
from app.db.session import get_session_factory
from tests.integration.test_fulltext_api import _client, _found
from tests.integration.test_workspaces_api import _create_ws, _headers, _seed_analysed_paper, _token


def _library(client: TestClient, token: str) -> dict:
    resp = client.get("/api/v1/papers", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_readers_uploads_are_in_their_library_and_no_one_elses(tmp_path: Path, normal_paper_pdf_bytes: bytes) -> None:
    client = _client(tmp_path)
    alice, bob = _token(client, "alice@example.com"), _token(client, "bob@example.com")
    up = client.post(
        "/api/v1/papers/upload", files={"file": ("paper.pdf", normal_paper_pdf_bytes, "application/pdf")}, headers=_headers(alice)
    ).json()

    lib = _library(client, alice)
    [paper] = lib["papers"]
    assert paper["id"] == up["paper_id"] and paper["roles"] == ["uploaded"]
    assert paper["title"] and paper["coverage"]["state"] == "full_text" and paper["analyzed"] is False
    assert paper["workspaces"] == [] and paper["last_active_at"].endswith("+00:00")
    assert lib["counts"]["papers"] == 1 and lib["counts"]["uploaded"] == 1
    assert _library(client, bob)["papers"] == []

    # the same PDF uploaded by another reader is one paper, in both libraries
    again = client.post(
        "/api/v1/papers/upload", files={"file": ("same.pdf", normal_paper_pdf_bytes, "application/pdf")}, headers=_headers(bob)
    ).json()
    assert again["deduplicated"] is True and again["paper_id"] == up["paper_id"]
    assert [p["id"] for p in _library(client, bob)["papers"]] == [up["paper_id"]]

    # an upload without signing in still works; it is just nobody's
    anon = client.post("/api/v1/papers/upload", files={"file": ("paper.pdf", normal_paper_pdf_bytes, "application/pdf")})
    assert anon.status_code == 202
    assert client.get("/api/v1/papers").status_code == 401


def test_the_library_holds_the_readers_seeds_analyses_and_workspace_papers(tmp_path: Path) -> None:
    client = _client(tmp_path)
    token = _token(client, "carol@example.com")
    me = client.get("/api/v1/me", headers=_headers(token)).json()
    _seed_analysed_paper()
    _found("pap_member", publisher="IEEE", year=2024)
    _found("pap_searched")
    ws = _create_ws(client, token, title="Campus transit")
    assert client.post(f"/api/v1/workspaces/{ws['workspace_id']}/papers", json={"paper_ids": ["pap_member"]}, headers=_headers(token)).status_code in (200, 201)
    db = get_session_factory()()
    try:
        db.add(SearchRunORM(id="run_lib", owner_id=me["id"], seed_paper_id="pap_searched"))
        db.commit()
        # what analysing it records (the analyze route passes the reader)
        profile = db.get(ResearchProfileORM, "prof_pap_seed")
        assert profile is not None
        profile.owner_id = me["id"]
        db.commit()
    finally:
        db.close()

    lib = _library(client, token)
    by_id = {p["id"]: p for p in lib["papers"]}
    assert set(by_id) == {"pap_seed", "pap_member", "pap_searched"}
    assert set(by_id["pap_seed"]["roles"]) == {"seed", "analyzed"} and by_id["pap_seed"]["analyzed"] is True
    assert by_id["pap_member"]["roles"] == ["collected"] and by_id["pap_member"]["publisher"] == "IEEE"
    assert by_id["pap_member"]["workspaces"] == [{"workspace_id": ws["workspace_id"], "title": "Campus transit"}]
    assert by_id["pap_searched"]["roles"] == ["searched"] and by_id["pap_searched"]["last_run_id"] == "run_lib"
    assert lib["counts"] == {"papers": 3, "uploaded": 0, "analyzed": 1, "in_workspaces": 2, "discovery_runs": 1, "workspaces": 1}
    # most recently touched first
    stamps = [p["last_active_at"] for p in lib["papers"]]
    assert stamps == sorted(stamps, reverse=True)
