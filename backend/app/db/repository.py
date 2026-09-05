"""Persistence mapping between domain (Pydantic) models and ORM rows.

Keeps app/services/ingest/* free of SQLAlchemy imports -- the pipeline
builds domain objects, and this module is the only place that knows how
they are stored (Architecture §2: deterministic storage code is its own
concern, separate from parsing logic).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import JobORM, PaperChunkORM, PaperORM
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.jobs import Job, JobKind, JobStatus
from app.domain.paper import ParsedDocument
from app.security.pdf_sanitizer import PdfFileMeta

# ---------------------------------------------------------------------------
# Paper
# ---------------------------------------------------------------------------


def paper_from_ingest(
    paper_id: str,
    meta: PdfFileMeta,
    parsed: ParsedDocument,
    pdf_path: str,
    title_hash: str = "",
    source: str = "upload",
) -> PaperORM:
    return PaperORM(
        id=paper_id,
        title=parsed.title or "(untitled)",
        title_hash=title_hash,
        authors=parsed.authors,
        has_full_text=True,
        pdf_path=pdf_path,
        pdf_sha256=meta.sha256,
        page_count=meta.page_count,
        parse_confidence=parsed.parse_confidence.value,
        source=source,
        sections=[s.model_dump(mode="json") for s in parsed.sections],
        tables=[t.model_dump(mode="json") for t in parsed.tables],
        references=[r.model_dump(mode="json") for r in parsed.references],
        warnings=parsed.warnings,
    )


def save_paper(db: Session, paper: PaperORM) -> PaperORM:
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper


def get_paper(db: Session, paper_id: str) -> PaperORM | None:
    return db.get(PaperORM, paper_id)


def find_paper_by_sha256(db: Session, sha256: str) -> PaperORM | None:
    return db.execute(select(PaperORM).where(PaperORM.pdf_sha256 == sha256)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# PaperChunk
# ---------------------------------------------------------------------------


def _chunk_orm_from_domain(chunk: PaperChunk) -> PaperChunkORM:
    return PaperChunkORM(
        id=chunk.chunk_id,
        paper_id=chunk.paper_id,
        workspace_id=chunk.workspace_id,
        section=chunk.section,
        section_order=chunk.section_order,
        page=chunk.page,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        kind=chunk.kind.value,
        text=chunk.text,
        token_count=chunk.token_count,
        embedding_ref=chunk.embedding_ref,
    )


def _chunk_domain_from_orm(row: PaperChunkORM) -> PaperChunk:
    return PaperChunk(
        chunk_id=row.id,
        paper_id=row.paper_id,
        workspace_id=row.workspace_id,
        section=row.section,
        section_order=row.section_order,
        page=row.page,
        char_start=row.char_start,
        char_end=row.char_end,
        kind=ChunkKind(row.kind),
        text=row.text,
        token_count=row.token_count,
        embedding_ref=row.embedding_ref,
    )


def save_chunks(db: Session, chunks: list[PaperChunk]) -> None:
    if not chunks:
        return
    db.add_all([_chunk_orm_from_domain(c) for c in chunks])
    db.commit()


def get_chunks_for_paper(db: Session, paper_id: str) -> list[PaperChunk]:
    rows = (
        db.execute(select(PaperChunkORM).where(PaperChunkORM.paper_id == paper_id).order_by(PaperChunkORM.id))
        .scalars()
        .all()
    )
    return [_chunk_domain_from_orm(r) for r in rows]


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


def _job_orm_from_domain(job: Job) -> JobORM:
    return JobORM(
        id=job.job_id,
        owner_id=job.owner_id,
        workspace_id=job.workspace_id,
        kind=job.kind.value,
        status=job.status.value,
        progress=job.progress,
        result_ref=job.result_ref,
        error=job.error,
    )


def _job_domain_from_orm(row: JobORM) -> Job:
    return Job(
        job_id=row.id,
        owner_id=row.owner_id,
        workspace_id=row.workspace_id,
        kind=JobKind(row.kind),
        status=JobStatus(row.status),
        progress=row.progress or {},
        result_ref=row.result_ref,
        error=row.error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def create_job(db: Session, job: Job) -> Job:
    db.add(_job_orm_from_domain(job))
    db.commit()
    return job


def get_job(db: Session, job_id: str) -> Job | None:
    row = db.get(JobORM, job_id)
    return _job_domain_from_orm(row) if row else None


def update_job(
    db: Session,
    job_id: str,
    *,
    status: JobStatus | None = None,
    progress: dict[str, str] | None = None,
    result_ref: str | None = None,
    error: str | None = None,
) -> Job | None:
    row = db.get(JobORM, job_id)
    if row is None:
        return None
    if status is not None:
        row.status = status.value
    if progress is not None:
        row.progress = {**(row.progress or {}), **progress}
    if result_ref is not None:
        row.result_ref = result_ref
    if error is not None:
        row.error = error
    db.commit()
    db.refresh(row)
    return _job_domain_from_orm(row)
