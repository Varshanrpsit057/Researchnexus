"""A paper's text from a PDF the reader has (remediation, 2026-10-02):
attaching a PDF to a paper discovery found, and reading an upload again with
the current reader."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import delete

from app.db import repository as repo
from app.db.models import PaperChunkORM
from app.db.session import get_session_factory
from tests.auth_helpers import ANONYMOUS
from tests.fixtures.make_fixtures import IEEE_ABSTRACT_WORDS, IEEE_DOI
from tests.integration.test_fulltext_api import _client, _found
from tests.integration.test_workspaces_api import _headers, _token


def test_a_discovered_paper_gains_its_full_text_from_a_pdf_the_reader_uploads(tmp_path: Path, ieee_style_pdf_bytes: bytes) -> None:
    client = _client(tmp_path)
    token = _token(client)
    _found("pap_paywalled", doi="10.1109/example.1", abstract="The source's abstract.")
    assert client.get("/api/v1/papers/pap_paywalled").json()["coverage"]["state"] == "abstract_only"

    resp = client.post(
        "/api/v1/papers/pap_paywalled/pdf",
        files={"file": ("paper.pdf", ieee_style_pdf_bytes, "application/pdf")},
        headers=_headers(token),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["coverage"]["state"] == "full_text" and body["coverage"]["source"] == "upload"
    assert body["outcome"]["chunks"] > 0 and body["outcome"]["abstract_found"] is True

    paper = client.get("/api/v1/papers/pap_paywalled").json()
    assert paper["title"] == "Found pap_paywalled"  # the discovery record's title stays
    assert paper["has_full_text"] is True
    db = get_session_factory()()
    try:
        chunks = repo.get_chunks_for_paper(db, "pap_paywalled")
        assert any("Public transportation within university campuses" in c.text for c in chunks)
        stored = repo.get_paper(db, "pap_paywalled")
        assert stored is not None and stored.doi == "10.1109/example.1"  # the record's DOI stays
    finally:
        db.close()

    # reading that PDF again keeps the record's title too (2026-10-07: it used to take the PDF's)
    assert client.post("/api/v1/papers/pap_paywalled/reread", headers=_headers(token)).status_code == 200
    assert client.get("/api/v1/papers/pap_paywalled").json()["title"] == "Found pap_paywalled"

    assert client.post("/api/v1/papers/pap_none/pdf", files={"file": ("x.pdf", ieee_style_pdf_bytes, "application/pdf")}, headers=_headers(token)).status_code == 404
    not_pdf = client.post("/api/v1/papers/pap_paywalled/pdf", files={"file": ("x.pdf", b"hello", "application/pdf")}, headers=_headers(token))
    assert not_pdf.status_code in (415, 422)


def test_an_upload_is_read_again_with_the_current_reader(tmp_path: Path, ieee_style_pdf_bytes: bytes) -> None:
    client = _client(tmp_path)
    token = _token(client)
    up = client.post("/api/v1/papers/upload", files={"file": ("onboard.pdf", ieee_style_pdf_bytes, "application/pdf")})
    pid = up.json()["paper_id"]
    first = client.get(f"/api/v1/papers/{pid}").json()
    assert first["doi"] == IEEE_DOI.lower() and first["has_abstract"] is True

    # what an earlier reader left behind: one chunk of glued text, no abstract
    db = get_session_factory()()
    try:
        db.execute(delete(PaperChunkORM).where(PaperChunkORM.paper_id == pid))
        paper = repo.get_paper(db, pid)
        assert paper is not None
        paper.abstract = None
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/api/v1/papers/{pid}/reread", headers=_headers(token))
    assert resp.status_code == 200, resp.text
    assert resp.json()["outcome"]["abstract_found"] is True
    db = get_session_factory()()
    try:
        reread = repo.get_paper(db, pid)
        assert reread is not None and reread.abstract == " ".join(IEEE_ABSTRACT_WORDS)
        assert any("time management" in c.text for c in repo.get_chunks_for_paper(db, pid))
    finally:
        db.close()

    assert client.post("/api/v1/papers/pap_missing/reread", headers=_headers(token)).status_code == 404
    _found("pap_discovered")
    no_pdf = client.post("/api/v1/papers/pap_discovered/reread", headers=_headers(token))
    assert no_pdf.status_code == 409 and no_pdf.json()["detail"]["error"]["code"] == "no_stored_pdf"
    assert client.post(f"/api/v1/papers/{pid}/reread", headers=ANONYMOUS).status_code == 401


def test_an_upload_whose_doi_discovery_already_holds_is_still_saved(tmp_path: Path, ieee_style_pdf_bytes: bytes) -> None:
    # the same article found by discovery first: DOIs are unique, so the upload goes without it
    client = _client(tmp_path)
    token = _token(client)
    _found("pap_found_first", doi=IEEE_DOI.lower())
    up = client.post("/api/v1/papers/upload", files={"file": ("onboard.pdf", ieee_style_pdf_bytes, "application/pdf")})
    pid = up.json()["paper_id"]
    paper = client.get(f"/api/v1/papers/{pid}").json()
    assert paper["has_full_text"] is True and paper["doi"] is None
    assert client.post(f"/api/v1/papers/{pid}/reread", headers=_headers(token)).status_code == 200


def test_a_profile_extracted_before_the_paper_was_read_correctly_shows_its_real_abstract(tmp_path: Path, ieee_style_pdf_bytes: bytes) -> None:
    from app.domain.profile import ProfileField, ResearchProfile

    client = _client(tmp_path)
    pid = client.post("/api/v1/papers/upload", files={"file": ("onboard.pdf", ieee_style_pdf_bytes, "application/pdf")}).json()["paper_id"]
    db = get_session_factory()()
    try:
        # what an earlier read left: the first lines of the body standing in for the abstract
        repo.upsert_profile(db, ResearchProfile(
            profile_id="prof_old", paper_id=pid, title="OnBoard", abstract="I. INTRODUCTION Students rely on campus buses",
            domain=ProfileField(value="transport"), research_problem=ProfileField(value="late buses"),
        ))
    finally:
        db.close()
    profile = client.get(f"/api/v1/papers/{pid}/profile").json()
    assert profile["abstract"] == " ".join(IEEE_ABSTRACT_WORDS)
    assert profile["abstract_found"] is True
    assert profile["summary"] and profile["summary"] in profile["abstract"]  # verbatim, from the real abstract
