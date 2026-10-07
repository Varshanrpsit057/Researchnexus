"""A trail between a workspace's own papers and its seed (remediation,
2026-10-02): papers the reader added are connected the way a discovery
run's are, from their reference lists and discovery's own signals."""

from __future__ import annotations

from pathlib import Path

from app.db import repository as repo
from app.db.models import PaperORM
from app.db.session import get_session_factory
from app.services.normalize.canonical import title_hash
from tests.integration.test_workspaces_api import (
    _create_ws,
    _headers,
    _make_client,
    _seed_analysed_paper,
    _token,
)


def _paper(pid: str, title: str, year: int, references: list[str] | None = None) -> None:
    db = get_session_factory()()
    try:
        repo.save_paper(
            db,
            PaperORM(
                id=pid,
                title=title,
                title_hash=title_hash(title),
                year=year,
                abstract=f"{title}. A study of retrieval for grounding answers.",
                source="upload",
                has_full_text=True,
                references=[{"raw_text": r, "order": i} for i, r in enumerate(references or [])],
            ),
        )
    finally:
        db.close()


def _edges(client, wid: str, token: str) -> list[dict]:  # noqa: ANN001
    groups = client.get(f"/api/v1/workspaces/{wid}/trail?state=all", headers=_headers(token)).json()["groups"]
    return [item["edge"] for items in groups.values() for item in items]


def test_a_workspace_of_the_readers_own_papers_gets_a_trail_and_keeps_its_decisions(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    token = _token(client)
    _seed_analysed_paper()
    db = get_session_factory()()
    try:
        seed = repo.get_paper(db, "pap_seed")
        assert seed is not None
        seed.year = 2024
        # the seed's own bibliography lists the older paper
        seed.references = [{"raw_text": "A. Author. Dense Passage Retrieval for Questions. 2019.", "order": 0}]
        db.commit()
    finally:
        db.close()
    _paper("pap_old", "Dense Passage Retrieval for Questions", 2019)
    _paper("pap_new", "Grounded Answers with Retrieval Augmented Generation", 2025, ["X. Y. Retrieval-Augmented Generation. 2024."])
    ws = _create_ws(client, token)
    wid = ws["workspace_id"]
    added = client.post(f"/api/v1/workspaces/{wid}/papers", json={"paper_ids": ["pap_old", "pap_new"]}, headers=_headers(token))
    assert added.status_code in (200, 201), added.text
    assert _edges(client, wid, token) == []  # no trail before it is built

    built = client.post(f"/api/v1/workspaces/{wid}/trail/build", headers=_headers(token))
    assert built.status_code == 200, built.text
    body = built.json()
    assert body["papers"] == 2 and body["edges"] >= 1

    edges = _edges(client, wid, token)
    by_target = {(e["target_paper_id"], e["relationship_type"]) for e in edges}
    assert ("pap_old", "FOUNDATIONAL") in by_target  # the seed cites it, and it is older
    edge_id = next(e["edge_id"] for e in edges if e["target_paper_id"] == "pap_old")

    # a decision survives a rebuild, and nothing is duplicated
    assert client.post(f"/api/v1/workspaces/{wid}/trail/{edge_id}", json={"user_state": "accepted"}, headers=_headers(token)).status_code == 200
    again = client.post(f"/api/v1/workspaces/{wid}/trail/build", headers=_headers(token))
    assert again.status_code == 200
    edges_again = _edges(client, wid, token)
    assert len(edges_again) == len(edges)
    assert next(e for e in edges_again if e["edge_id"] == edge_id)["user_state"] == "accepted"

    # a workspace of only its seed, another reader, no sign-in
    lone = _create_ws(client, token, title="Seed only")
    assert client.post(f"/api/v1/workspaces/{lone['workspace_id']}/trail/build", headers=_headers(token)).status_code == 409
    other = _token(client, "someone-else@example.com")
    assert client.post(f"/api/v1/workspaces/{wid}/trail/build", headers=_headers(other)).status_code == 404
    assert client.post(f"/api/v1/workspaces/{wid}/trail/build").status_code == 401
