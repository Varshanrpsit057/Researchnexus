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

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repository as repo
from app.db.session import get_db, get_session_factory
from app.deps import CurrentUser, OptionalUser
from app.domain.jobs import Job, JobKind, JobStatus
from app.domain.ranking import RankingCriteria
from app.jobs.runner import complete_metadata, new_id, run_discover_related_job, run_ingest_job
from app.llm.client import LlmProviderError, describe_provider_error
from app.routers import jobs as jobs_router
from app.security.pdf_sanitizer import PdfValidationError, validate_upload
from app.services.fulltext.retrieve import coverage_of, retrieve_full_text
from app.services.ingest.reread import (
    NoStoredPdf,
    PaperNotFound,
    TextOutcome,
    attach_pdf,
    reread_stored_pdf,
)
from app.services.library import build_library
from app.services.metadata.publishers import preferred_set
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
    uploader: OptionalUser,
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

    # the upload is credited to the signed-in reader: it is in their library (remediation, 2026-10-06)
    owner_id = uploader.id if uploader is not None else "usr_dev"
    existing = repo.find_paper_by_sha256(db, meta.sha256)
    if existing is not None:
        if uploader is not None:
            # already read: nothing to do but record that this reader has it too
            repo.create_job(
                db,
                Job(job_id=new_id("job"), owner_id=owner_id, kind=JobKind.INGEST, status=JobStatus.SUCCEEDED, result_ref=existing.id),
            )
        return {"paper_id": existing.id, "file": file_summary, "job": None, "deduplicated": True}

    paper_id = new_id("pap")
    job_id = new_id("job")
    repo.create_job(db, Job(job_id=job_id, owner_id=owner_id, workspace_id=None, kind=JobKind.INGEST))

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


@router.get("")
def list_library(db: DbSession, current_user: CurrentUser) -> dict[str, object]:
    """The reader's library: papers they uploaded, analysed, searched from or
    collected into a workspace, newest activity first."""
    return build_library(db, current_user.id)


@router.get("/{paper_id}")
def get_paper(paper_id: str, db: DbSession, reader: OptionalUser) -> dict[str, object]:
    paper = repo.get_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "paper not found"}})
    return {
        "id": paper.id,
        "title": paper.title,
        "authors": paper.authors,
        "year": paper.year,
        "venue": paper.venue,
        "publisher": paper.publisher,
        "doi": paper.doi,
        "arxiv_id": paper.arxiv_id,
        "url": paper.url,
        "has_full_text": paper.has_full_text,
        # an uploaded PDF, or a paper found by discovery (which has at most its abstract)
        "source": paper.source,
        "has_abstract": bool((paper.abstract or "").strip()),
        "parse_confidence": paper.parse_confidence,
        "page_count": paper.page_count,
        "sections": [
            {"title": s["title"], "order": s["order"], "page_span": [s["page_start"], s["page_end"]]}
            for s in paper.sections
        ],
        "tables": [{"caption": t.get("caption"), "page": t["page"]} for t in paper.tables],
        "warnings": paper.warnings,
        # what text the paper is read from (remediation Phase 7)
        "coverage": coverage_of(paper),
        # the signed-in reader's workspaces that hold it (2026-10-07); none for anyone else
        "workspaces": repo.workspaces_holding(db, paper.id, reader.id) if reader is not None else [],
    }


@router.post("/{paper_id}/fulltext")
async def retrieve_paper_full_text(paper_id: str, db: DbSession, settings: AppSettings, current_user: CurrentUser) -> dict:
    """Looks for this paper's full text now, at the open-access sources
    ResearchNexus reads from, and says what came of it."""
    if repo.get_paper(db, paper_id) is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "paper not found"}})
    outcome = await retrieve_full_text(db, paper_id, settings, force=True)
    paper = repo.get_paper(db, paper_id)
    assert paper is not None
    return {
        "outcome": {"status": outcome.status, "source": outcome.source, "reason": outcome.reason, "chunks": outcome.chunks},
        "coverage": coverage_of(paper),
    }


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "paper not found"}})


def _paper_text_answer(db: Session, paper_id: str, outcome: TextOutcome, metadata: dict[str, object]) -> dict:
    paper = repo.get_paper(db, paper_id)
    assert paper is not None
    return {
        "outcome": {"chunks": outcome.chunks, "sections": outcome.sections, "abstract_found": outcome.abstract_found, "doi": outcome.doi},
        "metadata": metadata,
        "coverage": coverage_of(paper),
    }


@router.post("/{paper_id}/reread")
def reread_paper(paper_id: str, db: DbSession, settings: AppSettings, current_user: CurrentUser) -> dict:
    """Read an uploaded paper's stored PDF again with the current reader, and
    complete its record from its sources (remediation, 2026-10-02)."""
    try:
        outcome = reread_stored_pdf(db, paper_id, settings)
    except PaperNotFound as e:
        raise _not_found() from e
    except NoStoredPdf as e:
        raise HTTPException(
            status_code=409, detail={"error": {"code": "no_stored_pdf", "message": "this paper has no stored PDF to read again; upload it"}}
        ) from e
    metadata = complete_metadata(db, paper_id, settings) if settings.metadata_lookup else {}
    return _paper_text_answer(db, paper_id, outcome, metadata)


@router.post("/{paper_id}/pdf")
async def upload_paper_pdf(
    paper_id: str, db: DbSession, settings: AppSettings, current_user: CurrentUser, file: Annotated[UploadFile, File(...)]
) -> dict:
    """A PDF the reader has becomes this paper's full text -- for a paper
    discovery found, whose publisher's copy can't be fetched (remediation,
    2026-10-02)."""
    if repo.get_paper(db, paper_id) is None:
        raise _not_found()
    data = await file.read()
    try:
        outcome = await run_in_threadpool(attach_pdf, db, paper_id, data, file.filename or "paper.pdf", settings)
    except PdfValidationError as e:
        raise HTTPException(
            status_code=_ERROR_HTTP_STATUS.get(e.code, 422), detail={"error": {"code": e.code, "message": e.message}}
        ) from e
    return _paper_text_answer(db, paper_id, outcome, {})


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
    # full text when it has it, else its abstract (a paper found by discovery)
    if not paper.has_full_text and not (paper.abstract or "").strip():
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "conflict", "message": "paper has no text to analyse yet"}},
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

# the publishers a reader prefers (remediation, 2026-10-06): up to 30 names
PreferredPublishers = Annotated[
    list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]] | None,
    Field(default=None, max_length=30),
]


class DiscoverRequest(BaseModel):
    """How the results are to be ranked (remediation Phase 9); omitted, the
    initial weights rank them. `preferred_publishers` omitted is the default four."""

    criteria: RankingCriteria | None = None
    preferred_publishers: PreferredPublishers = None


class RerankRequest(BaseModel):
    run_id: str
    criteria: RankingCriteria
    preferred_publishers: PreferredPublishers = None


@router.post("/{paper_id}/discover-related", status_code=202)
def discover_related(
    paper_id: str,
    background_tasks: BackgroundTasks,
    db: DbSession,
    settings: AppSettings,
    current_user: CurrentUser,
    body: DiscoverRequest | None = None,
) -> dict:
    paper = repo.get_paper(db, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "paper not found"}})
    if repo.get_profile(db, paper_id) is None:
        raise HTTPException(
            status_code=409,
            detail={"error": {"code": "conflict", "message": "paper must be analysed first (call analyze)"}},
        )

    # a run of this seed already going -- the page refreshed, a second tab, a
    # double click -- is followed, never duplicated (remediation Phase 8)
    active = repo.active_discover_job(
        db, current_user.id, paper_id, fresh_since=datetime.now(timezone.utc) - jobs_router.STALE_AFTER
    )
    if active is not None:
        return {
            "job": {"job_id": active.job_id, "kind": "discover", "status": active.status.value, "poll_url": f"/api/v1/jobs/{active.job_id}"},
            "resumed": True,
        }

    criteria = (body.criteria if body else None) or RankingCriteria()
    preferred = list(preferred_set(body.preferred_publishers if body else None))
    job_id = new_id("job")
    repo.create_job(
        db,
        Job(
            job_id=job_id,
            owner_id=current_user.id,
            workspace_id=None,
            kind=JobKind.DISCOVER,
            progress={"seed_paper_id": paper_id, "ranking_criteria": criteria.model_dump(), "preferred_publishers": preferred},
        ),
    )
    background_tasks.add_task(
        run_discover_related_job, get_session_factory(), job_id, paper_id, current_user.id, settings, criteria.model_dump(), preferred
    )
    return {"job": {"job_id": job_id, "kind": "discover", "status": "queued", "poll_url": f"/api/v1/jobs/{job_id}"}, "resumed": False}


@router.post("/{paper_id}/related/rerank")
async def rerank_related(paper_id: str, body: RerankRequest, db: DbSession, settings: AppSettings, current_user: CurrentUser) -> dict:
    """Re-weigh a run's ranking with new criteria (remediation Phase 9): the
    saved signals are fused again, nothing is searched or recomputed, and the
    result is the same as a fresh ranking with these criteria. Returns the
    results as `GET .../related` does."""
    from app.services.ranking.pipeline import RankingRequired, rerank_with_weights

    run = repo.get_search_run(db, body.run_id)
    if run is None or run.seed_paper_id != paper_id:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "discovery run not found"}})
    try:
        await rerank_with_weights(
            db,
            run_id=body.run_id,
            weights=body.criteria.to_weights(),
            settings=settings,
            preferred_publishers=None if body.preferred_publishers is None else preferred_set(body.preferred_publishers),
        )
    except RankingRequired as e:
        raise HTTPException(
            status_code=409, detail={"error": {"code": "conflict", "message": "this run hasn't been ranked yet"}}
        ) from e
    return get_related(paper_id, body.run_id, db, current_user, settings)


@router.get("/{paper_id}/related")
def get_related(paper_id: str, run_id: str, db: DbSession, current_user: CurrentUser, settings: AppSettings) -> dict:
    from app.services.discovery.related import RunNotFound, assemble_related_results

    try:
        view = assemble_related_results(db, run_id)
    except RunNotFound as e:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "discovery run not found"}}) from e
    if view.seed_paper_id != paper_id:
        raise HTTPException(status_code=404, detail={"error": {"code": "not_found", "message": "run does not belong to this paper"}})
    run = repo.get_search_run(db, run_id)

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
                    "publisher": related_paper.publisher if related_paper else None,
                    "doi": related_paper.doi if related_paper else None,
                    "url": item.candidate.url,
                    # as the source gave it; the page shows it only when asked
                    "abstract": (related_paper.abstract if related_paper else None) or item.candidate.abstract,
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
            # the score a band starts at, so a paper's band can be explained
            "bands": {"high": settings.rank_band_high, "medium": settings.rank_band_medium},
            # what the ranking was weighted by (remediation Phase 9); null when its version doesn't say
            "ranking_criteria": (
                criteria.model_dump()
                if view.weights_version and (criteria := RankingCriteria.from_weights_version(view.weights_version))
                else None
            ),
            # the publishers its ranking preferred (remediation, 2026-10-06)
            "preferred_publishers": repo.run_preferred_publishers(run) if run else None,
            # how the run went, step by step (remediation Phase 8); null for runs saved before
            "report": run.report if run else None,
            "started_at": run.started_at.isoformat() if run else None,
            "finished_at": run.finished_at.isoformat() if run and run.finished_at else None,
        },
        "results": results,
    }
