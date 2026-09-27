"""`POST /api/v1/papers/upload`, `GET /api/v1/papers/{paper_id}` (Phase 2),
`POST /api/v1/papers/{paper_id}/analyze` and `PATCH /api/v1/papers/{paper_id}/
profile` (Phase 3) -- see docs/architecture/ResearchNexus_API_Specification.md
§4.

Upload validation (Stage S1) runs synchronously so the client gets an
immediate, specific error (413/415/422); the heavier structural parse +
chunking (Stage S2/S3) runs as a background job. `analyze` (Stage S4) is
synchronous (API spec: "usually < 15 s"); the optional async/202 fallback
for a slow provider is not implemented -- the spec marks it as conditional
("may return 202 + job"), not required.

`POST .../discover-related` and `GET .../related` (Roadmap Phase 15) are
the first HTTP path to the Phase 5/6/7 discovery/ranking/trail pipelines --
each of those modules was built and unit-tested but deliberately left
unwired to any route, by design, until a UI needed to call them. Both
routes are thin: all business logic stays in
`app/services/discovery/{pipeline,related}.py`,
`app/services/ranking/pipeline.py`, and `app/services/trail/pipeline.py`,
run through the same `ResearchOrchestrator.run_stage` telemetry wrapper
every other Phase 14 stage uses."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db, get_session_factory
from app.deps import CurrentUser
from app.domain.jobs import Job, JobKind
from app.jobs.runner import new_id, run_discover_related_job, run_ingest_job
from app.llm.client import LlmProviderError, describe_provider_error
from app.security.pdf_sanitizer import PdfValidationError, validate_upload
from app.services.profile.pipeline import NoWorkingLlmKey, run_profile_extraction
from app.services.profile.validator import ProfilePatchRequest, apply_patch

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


@router.get("/{paper_id}/profile")
def get_profile(paper_id: str, db: DbSession) -> dict[str, object]:
    # A thin passthrough to the already-stored ResearchProfile, added
    # alongside analyze() so a client can show a previously extracted
    # profile without re-running (and re-billing) the LLM extraction on
    # every page visit -- analyze() itself always re-extracts, by design,
    # so it is not a substitute for reading back what is already saved.
    if repo.get_paper(db, paper_id) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "paper not found"}})
    profile = repo.get_profile(db, paper_id)
    if profile is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "no profile extracted yet"}})
    return profile.model_dump(mode="json")


@router.post("/{paper_id}/analyze")
async def analyze_paper(paper_id: str, db: DbSession, settings: AppSettings, current_user: CurrentUser) -> dict[str, object]:
    paper = repo.get_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "paper not found"}})
    if not paper.has_full_text:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "conflict", "message": "paper has no extracted text yet"}},
        )

    try:
        result = await run_profile_extraction(db, paper, current_user, settings)
    except NoWorkingLlmKey as e:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "llm_key_required", "message": "no working LLM provider key saved"}},
        ) from e
    except LlmProviderError as e:
        raise HTTPException(
            status_code=502,
            detail={"error": {"code": "provider_error", "kind": e.kind.value, "message": describe_provider_error(e)}},
        ) from e

    return {
        "profile": result.profile.model_dump(mode="json"),
        "extraction_confidence": result.profile.extraction_confidence.value,
        "warnings": result.warnings,
    }


@router.patch("/{paper_id}/profile")
def patch_profile(
    paper_id: str, body: ProfilePatchRequest, db: DbSession, current_user: CurrentUser
) -> dict[str, object]:
    existing = repo.get_profile(db, paper_id)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"error": {"code": "not_found", "message": "no profile exists for this paper -- call analyze first"}},
        )
    patched = apply_patch(existing, **body.model_dump())
    stored = repo.upsert_profile(db, patched)
    return {"profile": stored.model_dump(mode="json")}

@router.post("/{paper_id}/discover-related", status_code=202)
def discover_related(
    paper_id: str, background_tasks: BackgroundTasks, db: DbSession, settings: AppSettings, current_user: CurrentUser
) -> dict:
    paper = repo.get_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "paper not found"}})
    if repo.get_profile(db, paper_id) is None:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "conflict", "message": "paper must be analysed first (call analyze)"}},
        )

    job_id = new_id("job")
    repo.create_job(db, Job(job_id=job_id, owner_id=current_user.id, workspace_id=None, kind=JobKind.DISCOVER))
    background_tasks.add_task(run_discover_related_job, get_session_factory(), job_id, paper_id, current_user.id, settings)
    return {"job": {"job_id": job_id, "kind": "discover", "status": "queued", "poll_url": f"/api/v1/jobs/{job_id}"}}


@router.get("/{paper_id}/related")
def get_related(paper_id: str, run_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    from app.services.discovery.related import RunNotFound, assemble_related_results

    try:
        view = assemble_related_results(db, run_id)
    except RunNotFound as e:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "discovery run not found"}}) from e
    if view.seed_paper_id != paper_id:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "run does not belong to this paper"}})

    results = []
    for item in view.results:
        related_paper = repo.get_paper(db, item.paper_id)
        ranking = item.ranking
        results.append(
            {
                "paper": {
                    "id": item.paper_id,
                    "title": related_paper.title if related_paper else item.candidate.title,
                    "authors": related_paper.authors if related_paper else item.candidate.authors,
                    "year": related_paper.year if related_paper else item.candidate.year,
                    "venue": related_paper.venue if related_paper else item.candidate.venue,
                    "doi": related_paper.doi if related_paper else None,
                    "url": item.candidate.url,
                },
                "discovery_methods": [m.value for m in item.candidate.discovery_methods],
                "citation_relationship": item.candidate.citation_relationship.value,
                "signals": ranking.signals.model_dump(mode="json") if ranking else None,
                "weights_version": ranking.weights_version if ranking else None,
                "fused_score": ranking.fused_score if ranking else None,
                "rerank_score": ranking.rerank_score if ranking else None,
                "final_rank": ranking.final_rank if ranking else None,
                "band": ranking.band.value if ranking else None,
                "explanation": ranking.explanation.model_dump(mode="json") if ranking else None,
            }
        )

    return {
        "run": {
            "run_id": view.run_id,
            "seed_paper_id": view.seed_paper_id,
            "strategies_succeeded": view.strategies_succeeded,
            "strategies_failed": view.strategies_failed,
            "counts": view.counts,
            "extra_citation_hop_used": view.extra_citation_hop_used,
            "weights_version": view.weights_version,
        },
        "results": results,
    }
