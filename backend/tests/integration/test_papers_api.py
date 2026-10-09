from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import create_app
from tests.auth_helpers import signed_in


def _make_client(tmp_path: Path, **settings_overrides: object) -> TestClient:
    db_path = tmp_path / "test.db"
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        data_dir=tmp_path,
        database_url=f"sqlite:///{db_path}",
        **settings_overrides,  # type: ignore[arg-type]
    )
    app = create_app(settings=settings)
    app.dependency_overrides[get_settings] = lambda: settings
    return signed_in(TestClient(app))


def _upload(client: TestClient, data: bytes, filename: str = "paper.pdf") -> httpx.Response:
    return client.post("/api/v1/papers/upload", files={"file": (filename, data, "application/pdf")})


def _wait_for_job(client: TestClient, job_id: str, timeout_s: float = 5.0) -> dict[str, object]:
    """TestClient runs BackgroundTasks before returning the upload response,
    so this should resolve on the first check; the retry loop is a safety
    net rather than a requirement."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        resp = client.get(f"/api/v1/jobs/{job_id}")
        assert resp.status_code == 200
        job = resp.json()
        if job["status"] in ("succeeded", "failed", "partial"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout_s}s")


def test_health(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_upload_normal_pdf_returns_202_with_job(tmp_path: Path, normal_paper_pdf_bytes: bytes) -> None:
    client = _make_client(tmp_path)
    resp = _upload(client, normal_paper_pdf_bytes)
    assert resp.status_code == 202
    body = resp.json()
    assert body["paper_id"].startswith("pap_")
    assert body["job"]["kind"] == "ingest"
    assert body["job"]["status"] == "queued"
    assert body["file"]["page_count"] >= 1


def test_upload_then_job_succeeds_then_get_paper(tmp_path: Path, normal_paper_pdf_bytes: bytes) -> None:
    client = _make_client(tmp_path)
    upload = _upload(client, normal_paper_pdf_bytes).json()
    job = _wait_for_job(client, upload["job"]["job_id"])
    assert job["status"] == "succeeded"
    assert job["result_ref"] == upload["paper_id"]

    paper_resp = client.get(f"/api/v1/papers/{upload['paper_id']}")
    assert paper_resp.status_code == 200
    paper = paper_resp.json()
    assert "Retrieval-Augmented Generation" in paper["title"]
    assert paper["has_full_text"] is True
    assert paper["parse_confidence"] in ("high", "medium")
    assert len(paper["sections"]) >= 4
    assert any(t["caption"] and "Table 1" in t["caption"] for t in paper["tables"])


def test_reupload_same_pdf_is_idempotent(tmp_path: Path, normal_paper_pdf_bytes: bytes) -> None:
    client = _make_client(tmp_path)
    first = _upload(client, normal_paper_pdf_bytes).json()
    _wait_for_job(client, first["job"]["job_id"])

    second_resp = _upload(client, normal_paper_pdf_bytes)
    assert second_resp.status_code == 202
    second = second_resp.json()
    assert second["paper_id"] == first["paper_id"]
    assert second["job"] is None
    assert second.get("deduplicated") is True


@pytest.mark.parametrize(
    "fixture_name,expected_status,expected_code",
    [
        ("not_a_pdf_bytes", 415, "unsupported_media_type"),
        ("corrupt_pdf_bytes", 422, "pdf_invalid"),
        ("encrypted_pdf_bytes", 422, "pdf_encrypted"),
        ("scanned_pdf_bytes", 422, "pdf_scanned"),
    ],
)
def test_upload_rejects_bad_pdfs_with_correct_status_and_code(
    tmp_path: Path, request: pytest.FixtureRequest, fixture_name: str, expected_status: int, expected_code: str
) -> None:
    data: bytes = request.getfixturevalue(fixture_name)
    client = _make_client(tmp_path)
    resp = _upload(client, data)
    assert resp.status_code == expected_status
    assert resp.json()["detail"]["error"]["code"] == expected_code


def test_upload_oversized_pdf_returns_413(tmp_path: Path, normal_paper_pdf_bytes: bytes) -> None:
    client = _make_client(tmp_path, max_pdf_mb=0)
    resp = _upload(client, normal_paper_pdf_bytes)
    assert resp.status_code == 413
    assert resp.json()["detail"]["error"]["code"] == "file_too_large"


def test_upload_too_many_pages_returns_422(tmp_path: Path, multi_page_pdf_factory) -> None:
    client = _make_client(tmp_path, max_pages=1)
    resp = _upload(client, multi_page_pdf_factory(3))
    assert resp.status_code == 422
    assert resp.json()["detail"]["error"]["code"] == "too_many_pages"


def test_get_nonexistent_paper_returns_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.get("/api/v1/papers/pap_does_not_exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "not_found"


def test_get_nonexistent_job_returns_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.get("/api/v1/jobs/job_does_not_exist")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error"]["code"] == "not_found"


def test_two_column_paper_end_to_end(tmp_path: Path, two_column_paper_pdf_bytes: bytes) -> None:
    client = _make_client(tmp_path)
    upload = _upload(client, two_column_paper_pdf_bytes).json()
    job = _wait_for_job(client, upload["job"]["job_id"])
    assert job["status"] == "succeeded"
    paper = client.get(f"/api/v1/papers/{upload['paper_id']}").json()
    assert paper["has_full_text"] is True
