"""Research profiles through the real API (remediation Phase 6): what a
reader gets back -- clean abstract, its summary, metric values only when the
evidence gives them -- including for profiles stored before refinement
existed, and analysis of a paper found by discovery (abstract only)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.db import repository as repo
from app.db.models import PaperORM
from app.db.session import get_session_factory
from app.domain.profile import (
    ProfileField,
    ProfileList,
    ProvenanceStatus,
    ResearchProfile,
    SourceSpan,
)
from app.services.normalize.canonical import title_hash
from tests.integration.test_analyze_api import (
    _auth_headers,
    _authed_client,
    _mock_llm,
    _save_working_key,
)

ABSTRACT = (
    "Abstract�In modern educational institutions, attendance tracking is slow. This paper proposes a face "
    "recognition system for classrooms. Experiments on 40 students reveal a recognition accuracy of 95.83% and a "
    "precision and recall of 96% and 93% respectively. © 2025 The Authors. Published by ELSEVIER B.V."
)


def _paper(pid: str, abstract: str | None) -> None:
    db = get_session_factory()()
    try:
        repo.save_paper(db, PaperORM(id=pid, title="Attendance", title_hash=title_hash(pid), abstract=abstract, has_full_text=False))
    finally:
        db.close()


def test_a_profile_stored_before_refinement_reads_back_refined(tmp_path: Path) -> None:
    client, token = _authed_client(tmp_path)
    _paper("pap_old", ABSTRACT)
    quote = "a precision and recall of 96% and 93% respectively"
    stored = ResearchProfile(
        profile_id="prof_old",
        paper_id="pap_old",
        grounding="abstract",
        title="Attendance",
        abstract=ABSTRACT,  # as the old pipeline stored it: label, publisher block and all
        domain=ProfileField(value="face recognition for attendance"),
        research_problem=ProfileField(value="attendance tracking is slow"),
        evaluation_metrics=ProfileList(
            items=[
                ProfileField(value="precision", source_span=SourceSpan(paper_id="pap_old", quote=quote), status=ProvenanceStatus.VERIFIED),
                ProfileField(value="recall", source_span=SourceSpan(paper_id="pap_old", quote=quote), status=ProvenanceStatus.VERIFIED),
                ProfileField(value="F1 score"),
            ]
        ),
    )
    db = get_session_factory()()
    try:
        repo.upsert_profile(db, stored)
    finally:
        db.close()

    body = client.get("/api/v1/papers/pap_old/profile", headers=_auth_headers(token)).json()
    assert body["abstract"].startswith("In modern educational institutions")
    assert body["abstract"].endswith("93% respectively.")
    assert body["abstract_found"] is True
    assert body["summary"] == (
        "This paper proposes a face recognition system for classrooms. Experiments on 40 students reveal a recognition "
        "accuracy of 95.83% and a precision and recall of 96% and 93% respectively."
    )
    assert body["domain"]["value"] == "Face recognition for attendance"
    assert [(m["value"], m["reported_value"]) for m in body["evaluation_metrics"]["items"]] == [
        ("Precision", {"text": "96%", "status": "verified"}),
        ("Recall", {"text": "93%", "status": "verified"}),
        ("F1 score", None),  # named without a value in any evidence: none is invented
    ]


def test_a_paper_found_by_discovery_is_analysed_from_its_abstract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, token = _authed_client(tmp_path)
    _paper("pap_found", ABSTRACT)
    _save_working_key(client, token, monkeypatch)
    extraction = {
        "domain": {"value": "Education technology", "quote": None},
        "research_problem": {"value": "attendance tracking is slow", "quote": "attendance tracking is slow"},
        "evaluation_metrics": {
            "items": [
                {"value": "Recognition accuracy", "quote": "a recognition accuracy of 95.83%", "result": "95.83%"},
                {"value": "Latency", "quote": "a recognition accuracy of 95.83%", "result": "120 ms"},
            ]
        },
    }
    _mock_llm(monkeypatch, json.dumps(extraction))

    resp = client.post("/api/v1/papers/pap_found/analyze", headers=_auth_headers(token))
    assert resp.status_code == 200, resp.text
    profile = resp.json()["profile"]
    assert profile["grounding"] == "abstract"
    assert profile["summary"].startswith("This paper proposes a face recognition system")
    assert profile["research_problem"]["status"] == "verified"
    assert [m["reported_value"] for m in profile["evaluation_metrics"]["items"]] == [
        {"text": "95.83%", "status": "verified"},
        {"text": "120 ms", "status": "unverified"},  # claimed, but not in its evidence: never shown as the result
    ]


def test_a_paper_with_no_text_at_all_cannot_be_analysed(tmp_path: Path) -> None:
    client, token = _authed_client(tmp_path)
    _paper("pap_empty", None)
    resp = client.post("/api/v1/papers/pap_empty/analyze", headers=_auth_headers(token))
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"]["message"] == "paper has no text to analyse yet"


def test_a_paper_says_where_it_came_from_and_whether_it_has_an_abstract(tmp_path: Path) -> None:
    client, token = _authed_client(tmp_path)
    _paper("pap_found2", ABSTRACT)
    db = get_session_factory()()
    try:
        db.query(PaperORM).filter_by(id="pap_found2").update({"source": "discovery"})
        db.commit()
    finally:
        db.close()
    body = client.get("/api/v1/papers/pap_found2", headers=_auth_headers(token)).json()
    assert (body["source"], body["has_full_text"], body["has_abstract"]) == ("discovery", False, True)
