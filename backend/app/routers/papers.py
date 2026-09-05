"""`POST /api/v1/papers/upload` and `GET /api/v1/papers/{paper_id}` -- see
docs/architecture/ResearchNexus_API_Specification.md §4.

Upload validation (Stage S1) runs synchronously so the client gets an
immediate, specific error (413/415/422); the heavier structural parse +
chunking (Stage S2/S3) runs as a background job."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db, get_session_factory
from app.domain.jobs import Job, JobKind
from app.jobs.runner import new_id, run_ingest_job
from app.security.pdf_sanitizer import PdfValidationError, validate_upload

router = APIRouter(prefix="/api/v1/papers", tags=["papers"])

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]

_ERROR_HTTP_STATUS = {
    "file_too_large": 413,
    "unsupported_media_type": 415,
    "pdf_invalid": 422,
    "pdf_encrypted": 422,
    "pdf_scanned": 422,
    "too_many_pages": 422,
}


@router.post("/upload", status_code=202)
async def upload_paper(
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: AppSettings,
    file: Annotated[UploadFile, File(...)],
) -> dict[str, object]:
    data = await file.read()
    try:
        meta = validate_upload(data, file.filename or "upload.pdf", settings)
    except PdfValidationError as e:
        status_code = _ERROR_HTTP_STATUS.get(e.code, 422)
        raise HTTPException(
            status_code=status_code, detail={"error": {"code": e.code, "message": e.message}}
        ) from e

    file_summary = {"sha256": meta.sha256, "size_bytes": meta.size_bytes, "page_count": meta.page_count}

    existing = repo.find_paper_by_sha256(db, meta.sha256)
    if existing is not None:
        return {"paper_id": existing.id, "file": file_summary, "job": None, "deduplicated": True}

    paper_id = new_id("pap")
    job_id = new_id("job")
    repo.create_job(db, Job(job_id=job_id, owner_id="usr_dev", workspace_id=None, kind=JobKind.INGEST))

    background_tasks.add_task(
        run_ingest_job,
        get_session_factory(),
        job_id,
        paper_id,
        data,
        file.filename or "upload.pdf",
        settings,
    )

    return {
        "paper_id": paper_id,
        "file": file_summary,
        "job": {"job_id": job_id, "kind": "ingest", "status": "queued", "poll_url": f"/api/v1/jobs/{job_id}"},
    }


@router.get("/{paper_id}")
def get_paper(paper_id: str, db: DbSession) -> dict[str, object]:
    paper = repo.get_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "paper not found"}})
    return {
        "id": paper.id,
        "title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "venue": paper.venue,
        "doi": paper.doi,
        "arxiv_id": paper.arxiv_id,
        "has_full_text": paper.has_full_text,
        "parse_confidence": paper.parse_confidence,
        "page_count": paper.page_count,
        "sections": [
            {"title": s["title"], "order": s["order"], "page_span": [s["page_start"], s["page_end"]]}
            for s in paper.sections
        ],
        "tables": [{"caption": t.get("caption"), "page": t["page"]} for t in paper.tables],
        "warnings": paper.warnings,
    }
