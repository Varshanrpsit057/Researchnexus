"""Persistence mapping between domain (Pydantic) models and ORM rows.

Keeps app/services/ingest/* free of SQLAlchemy imports -- the pipeline
builds domain objects, and this module is the only place that knows how
they are stored (Architecture §2: deterministic storage code is its own
concern, separate from parsing logic).
"""

from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import ColumnElement, Select, and_, case, delete, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.db.models import (
    ApiKeyORM,
    ChatMessageORM,
    ChatSessionORM,
    CitationORM,
    ClaimORM,
    ComparisonORM,
    JobORM,
    LlmCallORM,
    PaperChunkORM,
    PaperORM,
    PaperRelationshipORM,
    RankedPaperORM,
    ResearchDirectionORM,
    ResearchGapORM,
    ResearchProfileORM,
    SearchCandidateORM,
    SearchRunORM,
    StageRunORM,
    UserORM,
    WorkspaceORM,
    WorkspacePaperORM,
)
from app.domain.candidate import (
    CitationRelationship,
    DiscoveryStrategy,
    NormalizedCandidate,
    PaperCandidate,
    SearchRun,
)
from app.domain.chat import ChatMessage, ChatRole, ChatSession
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.citation import Citation, Claim
from app.domain.comparison import Comparison, ComparisonRow, ComparisonSchema
from app.domain.direction import DirectionUserState, ResearchDirection
from app.domain.gap import GapEvidence, GapType, GapUserState, ResearchGap
from app.domain.graph import ResearchGraph
from app.domain.jobs import Job, JobKind, JobStatus
from app.domain.orchestrator import StageName, StageRun
from app.domain.paper import ParsedDocument
from app.domain.profile import Confidence, ResearchProfile
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge, UserState
from app.domain.usage import LlmCall
from app.domain.user import ApiKeyRecord, ApiKeyStatus, LlmProvider, User
from app.domain.workspace import (
    AddedBy,
    Grounding,
    ResearchWorkspace,
    WorkspacePaper,
    WorkspacePaperRole,
)
from app.security.pdf_sanitizer import PdfFileMeta
from app.services.profile.refine import refine_profile

if TYPE_CHECKING:  # the ingest pipeline imports this module
    from app.services.ingest.pipeline import ParsedPdf

# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


def _user_domain_from_orm(row: UserORM) -> User:
    return User(
        id=row.id,
        email=row.email,
        auth_provider=row.auth_provider,
        auth_subject=row.auth_subject,
        created_at=row.created_at,
        default_provider=LlmProvider(row.default_provider) if row.default_provider else None,
    )


def create_user(db: Session, *, user_id: str, email: str) -> User:
    row = UserORM(id=user_id, email=email, auth_provider="local", auth_subject=email)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _user_domain_from_orm(row)


def get_user(db: Session, user_id: str) -> User | None:
    row = db.get(UserORM, user_id)
    return _user_domain_from_orm(row) if row else None


def get_user_by_email(db: Session, email: str) -> User | None:
    row = db.execute(select(UserORM).where(UserORM.email == email)).scalar_one_or_none()
    return _user_domain_from_orm(row) if row else None


def find_user_for_sign_in(db: Session, email: str) -> User | None:
    """The account an email signs in to: the one saved with exactly this
    spelling, else the oldest saved with any capitalisation of it. Accounts
    created before sign-in ignored case (remediation, 2026-10-06) keep their
    exact spelling, so none becomes unreachable."""
    exact = get_user_by_email(db, email)
    if exact is not None:
        return exact
    row = (
        db.execute(select(UserORM).where(func.lower(UserORM.email) == email.lower()).order_by(UserORM.created_at, UserORM.id))
        .scalars()
        .first()
    )
    return _user_domain_from_orm(row) if row else None


def set_default_provider(db: Session, user_id: str, provider: LlmProvider | None) -> User | None:
    row = db.get(UserORM, user_id)
    if row is None:
        return None
    row.default_provider = provider.value if provider else None
    db.commit()
    db.refresh(row)
    return _user_domain_from_orm(row)


# ---------------------------------------------------------------------------
# ApiKey
# ---------------------------------------------------------------------------


def _api_key_record_from_orm(row: ApiKeyORM) -> ApiKeyRecord:
    return ApiKeyRecord(
        id=row.id,
        owner_id=row.owner_id,
        provider=LlmProvider(row.provider),
        key_last4=row.key_last4,
        status=ApiKeyStatus(row.status),
        checked_at=row.checked_at,
        created_at=row.created_at,
    )


def upsert_api_key(
    db: Session,
    *,
    new_key_id: str,
    owner_id: str,
    provider: LlmProvider,
    key_ciphertext: bytes,
    key_last4: str,
    status: ApiKeyStatus,
    checked_at: datetime,
) -> ApiKeyRecord:
    row = db.execute(
        select(ApiKeyORM).where(ApiKeyORM.owner_id == owner_id, ApiKeyORM.provider == provider.value)
    ).scalar_one_or_none()
    if row is None:
        row = ApiKeyORM(id=new_key_id, owner_id=owner_id, provider=provider.value)
        db.add(row)
    row.key_ciphertext = key_ciphertext
    row.key_last4 = key_last4
    row.status = status.value
    row.checked_at = checked_at
    db.commit()
    db.refresh(row)
    return _api_key_record_from_orm(row)


def get_api_key_ciphertext(db: Session, owner_id: str, provider: LlmProvider) -> bytes | None:
    row = db.execute(
        select(ApiKeyORM).where(ApiKeyORM.owner_id == owner_id, ApiKeyORM.provider == provider.value)
    ).scalar_one_or_none()
    return row.key_ciphertext if row else None


def list_api_keys(db: Session, owner_id: str) -> list[ApiKeyRecord]:
    """In the order they were saved -- the fallback order when no default is set."""
    rows = db.execute(
        select(ApiKeyORM).where(ApiKeyORM.owner_id == owner_id).order_by(ApiKeyORM.created_at, ApiKeyORM.id)
    ).scalars().all()
    return [_api_key_record_from_orm(r) for r in rows]


def pick_working_key(db: Session, owner_id: str, preferred: LlmProvider | None = None) -> ApiKeyRecord | None:
    """The key every LLM stage uses: the user's default provider when its key
    works, else the first working key saved."""
    working = [k for k in list_api_keys(db, owner_id) if k.status == ApiKeyStatus.WORKING]
    return next((k for k in working if k.provider == preferred), None) or (working[0] if working else None)


def has_working_api_key(db: Session, owner_id: str) -> bool:
    row = db.execute(
        select(ApiKeyORM).where(ApiKeyORM.owner_id == owner_id, ApiKeyORM.status == ApiKeyStatus.WORKING.value)
    ).first()
    return row is not None


def mark_api_key_failed(db: Session, owner_id: str, provider: LlmProvider) -> None:
    """The provider rejected the stored key on a real call: it is no longer
    a working key, so the next call picks another (or says none works)
    instead of failing the same way again. A later check can restore it."""
    row = db.execute(
        select(ApiKeyORM).where(ApiKeyORM.owner_id == owner_id, ApiKeyORM.provider == provider.value)
    ).scalar_one_or_none()
    if row is None:
        return
    row.status = ApiKeyStatus.FAILED.value
    row.checked_at = datetime.now(timezone.utc)
    db.commit()


def delete_api_key(db: Session, owner_id: str, provider: LlmProvider) -> bool:
    row = db.execute(
        select(ApiKeyORM).where(ApiKeyORM.owner_id == owner_id, ApiKeyORM.provider == provider.value)
    ).scalar_one_or_none()
    if row is None:
        return False
    db.delete(row)
    user = db.get(UserORM, owner_id)
    if user is not None and user.default_provider == provider.value:
        user.default_provider = None  # a default without a key would silently mean "first working key"
    db.commit()
    return True


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
        doi=parsed.doi,
        abstract=parsed.abstract,
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


def paper_titles(db: Session, paper_ids: Collection[str]) -> dict[str, str]:
    """Titles of many papers in one query (no other column is loaded)."""
    ids = list(paper_ids)
    out: dict[str, str] = {}
    for start in range(0, len(ids), 500):
        # a loop, not dict(result): a Result has .keys(), so dict() would index it
        for pid, title in db.execute(select(PaperORM.id, PaperORM.title).where(PaperORM.id.in_(ids[start : start + 500]))):
            out[pid] = title
    return out


def workspaces_holding(db: Session, paper_id: str, owner_id: str) -> list[dict[str, str]]:
    """The reader's workspaces a paper is in, by name."""
    rows = db.execute(
        select(WorkspaceORM.id, WorkspaceORM.title)
        .join(WorkspacePaperORM, WorkspacePaperORM.workspace_id == WorkspaceORM.id)
        .where(WorkspacePaperORM.paper_id == paper_id, WorkspaceORM.owner_id == owner_id)
        .order_by(WorkspaceORM.title)
    )
    return [{"workspace_id": wid, "title": title} for wid, title in rows]


def get_paper(db: Session, paper_id: str) -> PaperORM | None:
    return db.get(PaperORM, paper_id)


def doi_holder(db: Session, doi: str) -> str | None:
    """The paper that already has this DOI, if any (DOIs are unique: an
    upload and a discovered record of the same article can't both hold it)."""
    return db.execute(select(PaperORM.id).where(PaperORM.doi == doi)).scalar_one_or_none()


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


def attach_full_text(
    db: Session,
    paper_id: str,
    *,
    pdf_path: str | None,
    sha256: str | None,
    page_count: int | None,
    parse_confidence: str,
    sections: list[dict],
    tables: list[dict],
    references: list[dict],
    warnings: list[str],
    chunks: list[PaperChunk],
    source: str,
    url: str,
) -> None:
    """A paper found by discovery gains its full text (remediation Phase 7):
    its text, sections and chunks become the parsed document's, and every
    workspace holding it reads it from full text from now on. Its title,
    authors and year stay the discovery record's (richer than a PDF's
    metadata), and its abstract chunk stays: past answers cite it."""
    paper = db.get(PaperORM, paper_id)
    if paper is None:
        raise ValueError(f"no paper {paper_id}")
    if sha256 and (holder := find_paper_by_sha256(db, sha256)) is not None and holder.id != paper_id:
        sha256 = None  # the same PDF was uploaded as its own paper: the hash stays unique to that one
    abstract_chunk = f"chk_{paper_id}_abstract"
    db.execute(delete(PaperChunkORM).where(PaperChunkORM.paper_id == paper_id, PaperChunkORM.id != abstract_chunk))
    paper.has_full_text = True
    paper.pdf_path = pdf_path
    paper.pdf_sha256 = sha256
    paper.page_count = page_count
    paper.parse_confidence = parse_confidence
    paper.sections = sections
    paper.tables = tables
    paper.references = references
    paper.warnings = warnings
    paper.fulltext_status = "retrieved"
    paper.fulltext_source = source
    paper.fulltext_url = url[:1024]
    paper.fulltext_error = None
    paper.fulltext_checked_at = datetime.now(timezone.utc)
    db.add_all([_chunk_orm_from_domain(c) for c in chunks if c.chunk_id != abstract_chunk])
    for member in db.execute(select(WorkspacePaperORM).where(WorkspacePaperORM.paper_id == paper_id)).scalars():
        member.grounding = Grounding.FULL_TEXT.value
    db.commit()


def replace_text(db: Session, paper_id: str, parsed: ParsedPdf) -> None:
    """An uploaded paper's PDF read again (remediation, 2026-10-02): its
    text, sections and chunks become the new read's. Its record (title,
    authors, year) stays; past answers keep their claims, which now resolve
    to the corrected passages."""
    paper = db.get(PaperORM, paper_id)
    if paper is None:
        raise ValueError(f"no paper {paper_id}")
    doc = parsed.document
    db.execute(delete(PaperChunkORM).where(PaperChunkORM.paper_id == paper_id))
    paper.page_count = doc.page_count
    paper.parse_confidence = doc.parse_confidence.value
    paper.sections = [s.model_dump(mode="json") for s in doc.sections]
    paper.tables = [t.model_dump(mode="json") for t in doc.tables]
    paper.references = [r.model_dump(mode="json") for r in doc.references]
    paper.warnings = list(doc.warnings)
    db.add_all([_chunk_orm_from_domain(c) for c in parsed.chunks])
    db.commit()


def record_fulltext_attempt(
    db: Session, paper_id: str, *, status: str, source: str | None = None, url: str | None = None, error: str | None = None
) -> None:
    """What came of looking for a paper's full text, when it wasn't retrieved."""
    paper = db.get(PaperORM, paper_id)
    if paper is None:
        return
    paper.fulltext_status = status
    paper.fulltext_source = source
    paper.fulltext_url = url[:1024] if url else None
    paper.fulltext_error = error[:255] if error else None
    paper.fulltext_checked_at = datetime.now(timezone.utc)
    db.commit()


def get_chunks_for_paper(db: Session, paper_id: str) -> list[PaperChunk]:
    rows = (
        db.execute(select(PaperChunkORM).where(PaperChunkORM.paper_id == paper_id).order_by(PaperChunkORM.id))
        .scalars()
        .all()
    )
    return [_chunk_domain_from_orm(r) for r in rows]



def get_chunks_by_ids(db: Session, chunk_ids: list[str]) -> list[PaperChunk]:
    if not chunk_ids:
        return []
    rows = db.execute(select(PaperChunkORM).where(PaperChunkORM.id.in_(chunk_ids))).scalars().all()
    by_id = {r.id: _chunk_domain_from_orm(r) for r in rows}
    return [by_id[cid] for cid in chunk_ids if cid in by_id]

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


def latest_job(db: Session, workspace_id: str, kind: JobKind) -> Job | None:
    """A workspace's most recent job of one kind (to resume showing it, or not start a second)."""
    row = db.execute(
        select(JobORM)
        .where(JobORM.workspace_id == workspace_id, JobORM.kind == kind.value)
        .order_by(JobORM.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return _job_domain_from_orm(row) if row else None


def update_job(
    db: Session,
    job_id: str,
    *,
    status: JobStatus | None = None,
    progress: dict[str, Any] | None = None,
    result_ref: str | None = None,
    error: str | None = None,
) -> Job | None:
    """A cancelled job is final: once the owner has cancelled it, whatever
    its worker still writes is ignored (remediation Phase 8)."""
    row = db.get(JobORM, job_id)
    if row is None:
        return None
    db.refresh(row)  # the owner may have cancelled it from another session since
    if row.status == JobStatus.CANCELLED.value:
        return _job_domain_from_orm(row)
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


_ACTIVE_JOB_STATES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


def cancel_job(db: Session, job_id: str) -> Job | None:
    """Stop a queued or running job at its owner's request. Its worker sees
    the new status and stops; a job already finished keeps its outcome."""
    row = db.get(JobORM, job_id)
    if row is None:
        return None
    db.refresh(row)
    if row.status in _ACTIVE_JOB_STATES:
        row.status = JobStatus.CANCELLED.value
        row.progress = {**(row.progress or {}), "stage": "cancelled"}
        db.commit()
        db.refresh(row)
    return _job_domain_from_orm(row)


def fail_interrupted_jobs(db: Session) -> int:
    """At server start, mark every job still queued or running as failed:
    jobs run inside the server process, so none of them can still be going
    -- left alone, a page watching one would wait forever."""
    rows = db.execute(select(JobORM).where(JobORM.status.in_(_ACTIVE_JOB_STATES))).scalars().all()
    for row in rows:
        row.status = JobStatus.FAILED.value
        row.error = "The server restarted before this finished."
        row.progress = {**(row.progress or {}), "stage": "interrupted"}
    db.commit()
    return len(rows)


def active_discover_job(db: Session, owner_id: str, seed_paper_id: str, *, fresh_since: datetime) -> Job | None:
    """The owner's discovery run for this seed that is still going (heard
    from since `fresh_since`), so starting discovery again -- a refresh, a
    second tab, a double click -- follows it instead of starting a second."""
    rows = db.execute(
        select(JobORM)
        .where(
            JobORM.owner_id == owner_id,
            JobORM.kind == JobKind.DISCOVER.value,
            JobORM.status.in_(_ACTIVE_JOB_STATES),
            JobORM.updated_at >= fresh_since,
        )
        .order_by(JobORM.created_at.desc())
    ).scalars().all()
    row = next((r for r in rows if (r.progress or {}).get("seed_paper_id") == seed_paper_id), None)
    return _job_domain_from_orm(row) if row else None


# ---------------------------------------------------------------------------
# ResearchProfile
# ---------------------------------------------------------------------------


def _abstract_found(db: Session, paper_id: str) -> bool:
    """Whether the paper has a real abstract: one from its source, or an
    Abstract section in its PDF (a PDF without one stands in its body's first
    lines, which must not be shown as the abstract)."""
    paper = db.get(PaperORM, paper_id)
    if paper is None or (paper.abstract or "").strip():
        return True
    return any(
        re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", str(s.get("title", ""))).strip().lower() == "abstract"
        for s in (paper.sections or [])
    )


def _profile_domain_from_orm(db: Session, row: ResearchProfileORM) -> ResearchProfile:
    """Every profile is read refined (services/profile/refine.py): clean
    abstract, a summary, metric values from their evidence, one name per
    thing -- including profiles extracted before that existed."""
    profile = ResearchProfile.model_validate(row.profile_json)
    # the paper's own abstract, verbatim (its PDF's Abstract section, or its
    # source's), is the profile's: a profile extracted before the paper was
    # read correctly kept a stand-in from its first lines (remediation, 2026-10-02)
    paper = db.get(PaperORM, row.paper_id)
    if paper is not None and (paper.abstract or "").strip() and paper.abstract != profile.abstract:
        profile = profile.model_copy(update={"abstract": paper.abstract})
    return refine_profile(profile, abstract_found=_abstract_found(db, row.paper_id))


def upsert_profile(db: Session, profile: ResearchProfile, *, owner_id: str | None = None) -> ResearchProfile:
    """One profile per (paper_id, workspace_id) -- Data Model §13
    `UNIQUE(paper_id, workspace_id)`. Re-running `analyze` updates the
    existing canonical (workspace_id=None) row rather than creating a
    duplicate -- and, since it is the *same* logical resource, the original
    `profile_id` is preserved rather than replaced by whatever id the
    caller minted for this call (the caller doesn't know in advance
    whether it is creating or updating). Callers must use the returned
    `ResearchProfile`, not the one they passed in, as the source of truth."""
    workspace_clause = (
        ResearchProfileORM.workspace_id.is_(None)
        if profile.workspace_id is None
        else ResearchProfileORM.workspace_id == profile.workspace_id
    )
    row = db.execute(
        select(ResearchProfileORM).where(ResearchProfileORM.paper_id == profile.paper_id, workspace_clause)
    ).scalar_one_or_none()
    if row is None:
        row = ResearchProfileORM(id=profile.profile_id, paper_id=profile.paper_id, workspace_id=profile.workspace_id)
        db.add(row)
        stored_profile_id = profile.profile_id
    else:
        stored_profile_id = row.id

    payload = profile.model_dump(mode="json")
    payload["profile_id"] = stored_profile_id
    row.grounding = profile.grounding
    row.profile_json = payload
    row.extraction_confidence = profile.extraction_confidence.value
    row.extraction_model = profile.extraction_model
    if owner_id is not None:
        row.owner_id = owner_id  # who analysed it last: the paper is in their library
    db.commit()
    db.refresh(row)
    return _profile_domain_from_orm(db, row)


def get_profile(db: Session, paper_id: str, workspace_id: str | None = None) -> ResearchProfile | None:
    workspace_clause = (
        ResearchProfileORM.workspace_id.is_(None) if workspace_id is None else ResearchProfileORM.workspace_id == workspace_id
    )
    row = db.execute(
        select(ResearchProfileORM).where(ResearchProfileORM.paper_id == paper_id, workspace_clause)
    ).scalar_one_or_none()
    return _profile_domain_from_orm(db, row) if row else None


# ---------------------------------------------------------------------------
# Academic search (Phase 4): discovered papers + search runs + candidates
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def upsert_discovered_paper(db: Session, cand: NormalizedCandidate, *, commit: bool = True) -> str:
    """Link a normalised candidate to the global `papers` table, deduping by
    DOI -> versionless arXiv id -> normalised-title hash (Architecture §2).
    A new row is `source="discovery"`, `has_full_text=False`; an existing
    row only has its *empty* fields filled, never its richer data
    overwritten. `commit=False` leaves the commit to the caller (a discovery
    run saves its candidates in one transaction)."""
    doi = cand.external_ids.get("doi")
    arxiv_id = cand.external_ids.get("arxiv")

    row: PaperORM | None = None
    if doi:
        row = db.execute(select(PaperORM).where(PaperORM.doi == doi)).scalar_one_or_none()
    if row is None and arxiv_id:
        row = db.execute(select(PaperORM).where(PaperORM.arxiv_id == arxiv_id)).scalar_one_or_none()
    if row is None:
        row = db.execute(select(PaperORM).where(PaperORM.title_hash == cand.title_hash)).scalar_one_or_none()

    if row is None:
        row = PaperORM(
            id=_new_id("pap"),
            doi=doi,
            arxiv_id=arxiv_id,
            title=cand.title,
            title_hash=cand.title_hash,
            authors=list(cand.authors),
            year=cand.year,
            venue=cand.venue,
            abstract=cand.abstract,
            url=cand.url,
            publisher=cand.publisher,
            has_full_text=False,
            source="discovery",
        )
        db.add(row)
    else:
        if row.doi is None and doi:
            row.doi = doi
        if row.arxiv_id is None and arxiv_id:
            row.arxiv_id = arxiv_id
        if not row.authors and cand.authors:
            row.authors = list(cand.authors)
        if row.year is None and cand.year is not None:
            row.year = cand.year
        if row.venue is None and cand.venue:
            row.venue = cand.venue
        if row.abstract is None and cand.abstract:
            row.abstract = cand.abstract
        if row.url is None and cand.url:
            row.url = cand.url
        if not row.publisher and cand.publisher:
            row.publisher = cand.publisher
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()  # later lookups in the same transaction see this row
    return row.id


def _search_run_domain_from_orm(row: SearchRunORM) -> SearchRun:
    counts = row.counts or {}
    return SearchRun(
        run_id=row.id,
        owner_id=row.owner_id,
        workspace_id=row.workspace_id,
        seed_paper_id=row.seed_paper_id,
        strategies_requested=[DiscoveryStrategy(s) for s in row.strategies_requested],
        strategies_succeeded=[DiscoveryStrategy(s) for s in row.strategies_succeeded],
        strategies_failed=[DiscoveryStrategy(s) for s in row.strategies_failed],
        filters=dict(row.filters or {}),
        extra_citation_hop_used=row.extra_citation_hop_used,
        candidate_count_raw=counts.get("raw", 0),
        candidate_count_after_dedupe=counts.get("after_dedupe", 0),
        candidate_count_after_filter=counts.get("after_filter", 0),
        candidate_count_off_topic=counts.get("off_topic", 0),
        tokens_prompt=row.tokens_prompt,
        tokens_completion=row.tokens_completion,
        started_at=row.started_at,
        finished_at=row.finished_at,
        report=row.report,
    )


def create_search_run(db: Session, run: SearchRun, *, commit: bool = True) -> SearchRun:
    db.add(
        SearchRunORM(
            id=run.run_id,
            owner_id=run.owner_id,
            workspace_id=run.workspace_id,
            seed_paper_id=run.seed_paper_id,
            strategies_requested=[s.value for s in run.strategies_requested],
            strategies_succeeded=[s.value for s in run.strategies_succeeded],
            strategies_failed=[s.value for s in run.strategies_failed],
            filters=run.filters,
            extra_citation_hop_used=run.extra_citation_hop_used,
            counts={
                "raw": run.candidate_count_raw,
                "after_dedupe": run.candidate_count_after_dedupe,
                "after_filter": run.candidate_count_after_filter,
            },
            tokens_prompt=run.tokens_prompt,
            tokens_completion=run.tokens_completion,
            started_at=run.started_at,
            finished_at=run.finished_at,
            report=run.report,
        )
    )
    if commit:
        db.commit()
    return run


def get_search_run(db: Session, run_id: str) -> SearchRun | None:
    row = db.get(SearchRunORM, run_id)
    return _search_run_domain_from_orm(row) if row else None


def set_run_preferred_publishers(db: Session, run_id: str, publishers: Collection[str]) -> None:
    """Record the publishers a run's ranking preferred, with its filters (a
    JSON column, so no migration): the results page names them."""
    row = db.get(SearchRunORM, run_id)
    if row is None:
        return
    row.filters = {**(row.filters or {}), "preferred_publishers": list(publishers)}
    db.commit()


def run_preferred_publishers(run: SearchRun) -> list[str]:
    """The publishers a run's ranking preferred; runs ranked before the reader
    could choose (remediation, 2026-10-06) preferred the default four."""
    from app.services.metadata.publishers import TRUSTED_PUBLISHERS

    saved = (run.filters or {}).get("preferred_publishers")
    return list(saved) if isinstance(saved, list) else list(TRUSTED_PUBLISHERS)


def mark_candidates_off_topic(db: Session, run_id: str, candidate_ids: list[str]) -> None:
    """Record the ranking stage's relevance-floor drops: each candidate keeps
    its row but is no longer kept (reason "off_topic"), and the run counts
    them -- so the results page can say how many were set aside, and why."""
    if not candidate_ids:
        return
    rows = (
        db.execute(
            select(SearchCandidateORM).where(
                SearchCandidateORM.run_id == run_id, SearchCandidateORM.id.in_(candidate_ids)
            )
        )
        .scalars()
        .all()
    )
    dropped = 0
    for row in rows:
        if not row.filter_kept:
            continue
        row.filter_kept = False
        row.filter_reasons = [*(row.filter_reasons or []), "off_topic"]
        dropped += 1
    run = db.get(SearchRunORM, run_id)
    if run is not None and dropped:
        counts = dict(run.counts or {})
        counts["after_filter"] = max(0, counts.get("after_filter", 0) - dropped)
        counts["off_topic"] = counts.get("off_topic", 0) + dropped
        run.counts = counts  # a new dict, so the JSON column registers the change
    db.commit()


def add_search_candidate(
    db: Session,
    *,
    candidate_id: str,
    run_id: str,
    paper_id: str,
    discovery_methods: list[DiscoveryStrategy],
    possible_duplicate_of: str | None,
    provenance: dict,
    filter_kept: bool = True,
    raw_signals: dict | None = None,
    citation_relationship: CitationRelationship = CitationRelationship.NONE,
    citation_hops: int | None = None,
    filter_reasons: list[str] | None = None,
    commit: bool = True,
) -> None:
    db.add(
        SearchCandidateORM(
            id=candidate_id,
            run_id=run_id,
            paper_id=paper_id,
            discovery_methods=[m.value for m in discovery_methods],
            citation_relationship=citation_relationship.value,
            citation_hops=citation_hops,
            raw_signals=raw_signals or {},
            possible_duplicate_of=possible_duplicate_of,
            filter_kept=filter_kept,
            filter_reasons=filter_reasons or [],
            provenance=provenance,
        )
    )
    if commit:
        db.commit()


def _paper_external_ids(paper: PaperORM | None) -> dict[str, str]:
    if paper is None:
        return {}
    ids: dict[str, str] = {}
    if paper.doi:
        ids["doi"] = paper.doi
    if paper.arxiv_id:
        ids["arxiv"] = paper.arxiv_id
    return ids


def get_run_citation_relationships(db: Session, run_id: str) -> dict[str, str]:
    """Each candidate paper's citation relation to the run's seed, where it has one."""
    rows = db.execute(
        select(SearchCandidateORM.paper_id, SearchCandidateORM.citation_relationship).where(SearchCandidateORM.run_id == run_id)
    ).all()
    return {pid: rel for pid, rel in rows if rel and rel != CitationRelationship.NONE.value}


def get_search_candidates(db: Session, run_id: str) -> list[PaperCandidate]:
    rows = (
        db.execute(
            select(SearchCandidateORM).where(SearchCandidateORM.run_id == run_id).order_by(SearchCandidateORM.id)
        )
        .scalars()
        .all()
    )
    out: list[PaperCandidate] = []
    for r in rows:
        paper = db.get(PaperORM, r.paper_id)
        out.append(
            PaperCandidate(
                candidate_id=r.id,
                run_id=r.run_id,
                external_ids=_paper_external_ids(paper),
                title=paper.title if paper else "",
                authors=list(paper.authors) if paper and paper.authors else [],
                year=paper.year if paper else None,
                abstract=paper.abstract if paper else None,
                venue=paper.venue if paper else None,
                url=paper.url if paper else None,
                discovery_methods=[DiscoveryStrategy(m) for m in r.discovery_methods],
                citation_relationship=CitationRelationship(r.citation_relationship),
                citation_hops=r.citation_hops,
                preliminary_rank=r.preliminary_rank,
                possible_duplicate_of=r.possible_duplicate_of,
                filter_kept=r.filter_kept,
                filter_reasons=list(r.filter_reasons or []),
            )
        )
    return out


def get_search_candidate_provenance(db: Session, run_id: str) -> dict[str, dict]:
    rows = db.execute(select(SearchCandidateORM).where(SearchCandidateORM.run_id == run_id)).scalars().all()
    return {r.id: dict(r.provenance or {}) for r in rows}


# ---------------------------------------------------------------------------
# Ranking (Phase 6): ranked_papers, one row per (run, paper)
# ---------------------------------------------------------------------------


def get_search_candidate_paper_ids(db: Session, run_id: str) -> dict[str, str]:
    """`candidate_id -> paper_id` for a run -- the ranking pipeline needs
    the linked `papers.id` (which `get_search_candidates` does not carry) to
    persist `ranked_papers`."""
    rows = db.execute(
        select(SearchCandidateORM.id, SearchCandidateORM.paper_id).where(SearchCandidateORM.run_id == run_id)
    ).all()
    return {cid: pid for cid, pid in rows}


def _ranked_paper_domain_from_orm(row: RankedPaperORM) -> RankedPaper:
    return RankedPaper(
        candidate_id=row.candidate_id,
        signals=SignalScores(**(row.signals or {})),
        weights_version=row.weights_version,
        fused_score=row.fused_score,
        rerank_score=row.rerank_score,
        final_rank=row.final_rank,
        band=Confidence(row.band),
        explanation=RankingExplanation(**(row.explanation or {"bullet_reasons": [], "prose": ""})),
    )


def reset_run_candidates(db: Session, run_id: str) -> None:
    """Clear a run's candidates and ranking before they are rebuilt (a
    workspace's own-papers trail run is rebuilt in place)."""
    db.query(RankedPaperORM).filter(RankedPaperORM.run_id == run_id).delete()
    db.query(SearchCandidateORM).filter(SearchCandidateORM.run_id == run_id).delete()
    db.commit()


def save_ranked_papers(
    db: Session, run_id: str, ranked: list[RankedPaper], candidate_paper_ids: dict[str, str]
) -> None:
    """Replace the run's ranking result wholesale -- a re-rank of the same
    run supersedes the previous one."""
    db.query(RankedPaperORM).filter(RankedPaperORM.run_id == run_id).delete()
    for rp in ranked:
        db.add(
            RankedPaperORM(
                id=_new_id("rank"),
                run_id=run_id,
                candidate_id=rp.candidate_id,
                paper_id=candidate_paper_ids[rp.candidate_id],
                signals=rp.signals.model_dump(),
                weights_version=rp.weights_version,
                fused_score=rp.fused_score,
                rerank_score=rp.rerank_score,
                final_rank=rp.final_rank,
                band=rp.band.value,
                explanation=rp.explanation.model_dump(),
            )
        )
    db.commit()


def get_ranked_papers(db: Session, run_id: str) -> list[RankedPaper]:
    rows = (
        db.execute(
            select(RankedPaperORM).where(RankedPaperORM.run_id == run_id).order_by(RankedPaperORM.final_rank)
        )
        .scalars()
        .all()
    )
    return [_ranked_paper_domain_from_orm(r) for r in rows]


# ---------------------------------------------------------------------------
# Typed research trail (Phase 7): paper_relationships, run-scoped
# ---------------------------------------------------------------------------


def _trail_edge_domain_from_orm(row: PaperRelationshipORM) -> TrailEdge:
    return TrailEdge(
        edge_id=row.id,
        run_id=row.run_id,
        workspace_id=row.workspace_id,
        source_paper_id=row.source_paper_id,
        target_paper_id=row.target_paper_id,
        relationship_type=RelationshipType(row.relationship_type),
        detection_method=DetectionMethod(row.detection_method),
        rule_fired=row.rule_fired,
        llm_confirmed=row.llm_confirmed,
        evidence=[Evidence.model_validate(e) for e in (row.evidence or [])],
        supporting_references=list(row.supporting_references or []),
        confidence=Confidence(row.confidence),
        confidence_basis=dict(row.confidence_basis or {}),
        user_state=row.user_state,
        created_at=row.created_at,
    )


def _primary_rows(run_id: str) -> Select[Any]:  # Select's type parameter differs across SQLAlchemy 2.0 and 2.1
    """A run's own trail rows, not the copies later workspaces hold."""
    return select(PaperRelationshipORM).where(
        PaperRelationshipORM.run_id == run_id, PaperRelationshipORM.copied_from.is_(None)
    )


def save_trail_edges(db: Session, run_id: str, edges: list[TrailEdge]) -> None:
    """Replace this run's non-rejected trail edges. Rows a user has
    `rejected` are kept untouched (the builder already skips those keys, so
    a rejected edge is never re-proposed on a re-run). Only the run's
    primaries are touched: a rebuild never detaches a primary from the
    workspace that owns it, and never touches a workspace's own copies."""
    keep_ids = {e.edge_id for e in edges}
    for row in db.execute(_primary_rows(run_id)).scalars().all():
        if row.user_state == UserState.REJECTED.value:
            continue
        if row.id not in keep_ids:
            db.delete(row)

    for edge in edges:
        existing = db.get(PaperRelationshipORM, edge.edge_id)
        payload = dict(
            run_id=edge.run_id,
            source_paper_id=edge.source_paper_id,
            target_paper_id=edge.target_paper_id,
            relationship_type=edge.relationship_type.value,
            detection_method=edge.detection_method.value,
            rule_fired=edge.rule_fired,
            llm_confirmed=edge.llm_confirmed,
            evidence=[e.model_dump(mode="json") for e in edge.evidence],
            supporting_references=list(edge.supporting_references),
            confidence=edge.confidence.value,
            confidence_basis=edge.confidence_basis,
        )
        if existing is None:
            db.add(
                PaperRelationshipORM(
                    id=edge.edge_id,
                    workspace_id=edge.workspace_id,
                    user_state=edge.user_state,
                    created_at=edge.created_at,
                    **payload,
                )
            )
        elif existing.user_state != UserState.REJECTED.value:
            for key, value in payload.items():
                setattr(existing, key, value)
    db.commit()


def get_trail_edges(db: Session, run_id: str) -> list[TrailEdge]:
    """The run's own trail (its primaries), one row per connection."""
    rows = (
        db.execute(
            _primary_rows(run_id).order_by(
                PaperRelationshipORM.target_paper_id, PaperRelationshipORM.relationship_type
            )
        )
        .scalars()
        .all()
    )
    return [_trail_edge_domain_from_orm(r) for r in rows]


def get_rejected_trail_keys(db: Session, run_id: str) -> set[tuple[str, str]]:
    rows = db.execute(
        select(PaperRelationshipORM.target_paper_id, PaperRelationshipORM.relationship_type).where(
            PaperRelationshipORM.run_id == run_id,
            PaperRelationshipORM.copied_from.is_(None),
            PaperRelationshipORM.user_state == UserState.REJECTED.value,
        )
    ).all()
    return {(tgt, rtype) for tgt, rtype in rows}


def set_trail_edge_user_state(db: Session, edge_id: str, state: UserState) -> TrailEdge | None:
    row = db.get(PaperRelationshipORM, edge_id)
    if row is None:
        return None
    row.user_state = state.value
    db.commit()
    db.refresh(row)
    return _trail_edge_domain_from_orm(row)


# ---------------------------------------------------------------------------
# Research workspace (Phase 8): workspaces + workspace_papers, owner-scoped
# ---------------------------------------------------------------------------


def _workspace_paper_domain_from_orm(row: WorkspacePaperORM) -> WorkspacePaper:
    return WorkspacePaper(
        workspace_id=row.workspace_id,
        paper_id=row.paper_id,
        added_by=AddedBy(row.added_by),
        role=WorkspacePaperRole(row.role),
        grounding=Grounding(row.grounding),
        pinned=row.pinned,
        tags=list(row.tags or []),
        note=row.note,
        order=row.sort_order,
        ranking_snapshot=(
            RankedPaper.model_validate(row.ranking_snapshot) if row.ranking_snapshot else None
        ),
        added_at=row.added_at,
    )


def _workspace_domain_from_orm(row: WorkspaceORM, papers: list[WorkspacePaperORM]) -> ResearchWorkspace:
    ordered = sorted(papers, key=lambda pr: (pr.sort_order, pr.added_at))
    return ResearchWorkspace(
        workspace_id=row.id,
        owner_id=row.owner_id,
        title=row.title,
        seed_paper_id=row.seed_paper_id,
        seed_profile_id=row.seed_profile_id,
        papers=[_workspace_paper_domain_from_orm(pr) for pr in ordered],
        combined_index_path=row.combined_index_path,
        source_run_id=row.source_run_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _workspace_paper_orm(wp: WorkspacePaper, owner_id: str) -> WorkspacePaperORM:
    return WorkspacePaperORM(
        workspace_id=wp.workspace_id,
        paper_id=wp.paper_id,
        owner_id=owner_id,
        added_by=wp.added_by.value,
        role=wp.role.value,
        grounding=wp.grounding.value,
        pinned=wp.pinned,
        tags=list(wp.tags),
        note=wp.note,
        sort_order=wp.order,
        ranking_snapshot=wp.ranking_snapshot.model_dump(mode="json") if wp.ranking_snapshot else None,
        added_at=wp.added_at,
    )


def _owned_workspace_row(db: Session, workspace_id: str, owner_id: str) -> WorkspaceORM | None:
    """The single tenant gate: a row whose owner_id does not match is
    invisible (callers surface 404, never 403 -- API spec tenant isolation)."""
    row = db.get(WorkspaceORM, workspace_id)
    if row is None or row.owner_id != owner_id:
        return None
    return row


def create_workspace(db: Session, ws: ResearchWorkspace) -> ResearchWorkspace:
    db.add(
        WorkspaceORM(
            id=ws.workspace_id,
            owner_id=ws.owner_id,
            title=ws.title,
            seed_paper_id=ws.seed_paper_id,
            seed_profile_id=ws.seed_profile_id,
            source_run_id=ws.source_run_id,
            combined_index_path=ws.combined_index_path,
        )
    )
    for wp in ws.papers:
        db.add(_workspace_paper_orm(wp, ws.owner_id))
    db.commit()
    stored = get_workspace(db, ws.workspace_id, ws.owner_id)
    assert stored is not None  # just inserted
    return stored


def get_workspace(db: Session, workspace_id: str, owner_id: str) -> ResearchWorkspace | None:
    row = _owned_workspace_row(db, workspace_id, owner_id)
    if row is None:
        return None
    papers = (
        db.execute(select(WorkspacePaperORM).where(WorkspacePaperORM.workspace_id == workspace_id))
        .scalars()
        .all()
    )
    return _workspace_domain_from_orm(row, list(papers))


def list_workspaces(db: Session, owner_id: str) -> list[ResearchWorkspace]:
    rows = (
        db.execute(
            select(WorkspaceORM)
            .where(WorkspaceORM.owner_id == owner_id)
            .order_by(WorkspaceORM.created_at.desc())
        )
        .scalars()
        .all()
    )
    out: list[ResearchWorkspace] = []
    for row in rows:
        papers = (
            db.execute(select(WorkspacePaperORM).where(WorkspacePaperORM.workspace_id == row.id))
            .scalars()
            .all()
        )
        out.append(_workspace_domain_from_orm(row, list(papers)))
    return out


def update_workspace(
    db: Session,
    workspace_id: str,
    owner_id: str,
    *,
    title: str | None = None,
) -> ResearchWorkspace | None:
    row = _owned_workspace_row(db, workspace_id, owner_id)
    if row is None:
        return None
    if title is not None:
        row.title = title
    db.commit()
    return get_workspace(db, workspace_id, owner_id)


def set_workspace_index_path(
    db: Session, workspace_id: str, owner_id: str, path: str | None
) -> ResearchWorkspace | None:
    row = _owned_workspace_row(db, workspace_id, owner_id)
    if row is None:
        return None
    row.combined_index_path = path
    db.commit()
    return get_workspace(db, workspace_id, owner_id)


def delete_workspace(db: Session, workspace_id: str, owner_id: str) -> bool:
    row = _owned_workspace_row(db, workspace_id, owner_id)
    if row is None:
        return False
    # paper_relationships.workspace_id is a plain nullable column (no FK
    # cascade). The workspace's own copies go with it; primaries it owned
    # are released back to the run, without its review decisions, so the
    # next workspace to import the run starts its own review.
    for edge in (
        db.execute(select(PaperRelationshipORM).where(PaperRelationshipORM.workspace_id == workspace_id))
        .scalars()
        .all()
    ):
        if edge.copied_from is not None:
            db.delete(edge)
            continue
        edge.workspace_id = None
        edge.owner_id = None
        edge.user_state = UserState.PENDING.value
    db.delete(row)
    db.commit()
    return True


def add_workspace_paper(db: Session, wp: WorkspacePaper, owner_id: str) -> WorkspacePaper:
    """Insert one membership row. The (workspace_id, paper_id) PK makes a
    duplicate add raise IntegrityError -- the service layer decides whether
    that is an error or an idempotent no-op."""
    db.add(_workspace_paper_orm(wp, owner_id))
    db.commit()
    stored = get_workspace_paper(db, wp.workspace_id, wp.paper_id)
    assert stored is not None  # just inserted
    return stored


def get_workspace_paper(db: Session, workspace_id: str, paper_id: str) -> WorkspacePaper | None:
    row = db.get(WorkspacePaperORM, {"workspace_id": workspace_id, "paper_id": paper_id})
    return _workspace_paper_domain_from_orm(row) if row else None


def list_workspace_papers(db: Session, workspace_id: str) -> list[WorkspacePaper]:
    rows = (
        db.execute(
            select(WorkspacePaperORM)
            .where(WorkspacePaperORM.workspace_id == workspace_id)
            .order_by(WorkspacePaperORM.sort_order, WorkspacePaperORM.added_at)
        )
        .scalars()
        .all()
    )
    return [_workspace_paper_domain_from_orm(r) for r in rows]


def update_workspace_paper(
    db: Session, workspace_id: str, paper_id: str, changes: dict
) -> WorkspacePaper | None:
    """Apply only the keys present in changes (pinned / tags / note /
    order); the service layer has already normalised the values."""
    row = db.get(WorkspacePaperORM, {"workspace_id": workspace_id, "paper_id": paper_id})
    if row is None:
        return None
    if "pinned" in changes:
        row.pinned = bool(changes["pinned"])
    if "tags" in changes:
        row.tags = list(changes["tags"])
    if "note" in changes:
        row.note = changes["note"]
    if "order" in changes:
        row.sort_order = int(changes["order"])
    db.commit()
    db.refresh(row)
    return _workspace_paper_domain_from_orm(row)


def remove_workspace_paper(db: Session, workspace_id: str, paper_id: str) -> bool:
    row = db.get(WorkspacePaperORM, {"workspace_id": workspace_id, "paper_id": paper_id})
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def workspace_child_counts(db: Session, workspace_id: str) -> dict[str, int]:
    return workspaces_child_counts(db, [workspace_id])[workspace_id]


def workspaces_child_counts(db: Session, workspace_ids: Collection[str]) -> dict[str, dict[str, int]]:
    """What each workspace holds -- papers, connections, gaps, directions,
    comparisons -- for many workspaces in one grouped query per table (the
    workspace list used to run five queries per workspace: 2 s for 1,300).
    Rejected connections, gaps and directions are not counted."""
    counts = {wid: {"papers": 0, "edges": 0, "gaps": 0, "directions": 0, "comparisons": 0} for wid in workspace_ids}
    ids = list(counts)
    tables: list[tuple[str, Any, list[ColumnElement[bool]]]] = [
        ("papers", WorkspacePaperORM, []),
        ("edges", PaperRelationshipORM, [PaperRelationshipORM.user_state != UserState.REJECTED.value]),
        ("gaps", ResearchGapORM, [ResearchGapORM.user_state != GapUserState.REJECTED.value]),
        ("directions", ResearchDirectionORM, [ResearchDirectionORM.user_state != DirectionUserState.REJECTED.value]),
        ("comparisons", ComparisonORM, []),
    ]
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        for key, model, extra in tables:
            rows = db.execute(
                select(model.workspace_id, func.count()).where(model.workspace_id.in_(chunk), *extra).group_by(model.workspace_id)
            )
            for wid, n in rows:
                counts[wid][key] = int(n)
    return counts


def _copied_edge_id(primary_id: str, workspace_id: str) -> str:
    digest = hashlib.sha256(f"{primary_id}|{workspace_id}".encode()).hexdigest()
    return f"edge_{digest[:20]}"


def attach_run_edges_to_workspace(
    db: Session, *, run_id: str, workspace_id: str, owner_id: str
) -> int:
    """Give a workspace the run's Phase 7 trail (GET /workspaces/{id}/trail).

    A primary no workspace holds yet is stamped with this workspace. One
    another workspace already holds is *copied* for this one -- never moved:
    the copy starts unreviewed, and the other workspace keeps its rows and
    its decisions. Idempotent; returns how many edges the workspace gained.
    """
    attached = 0
    for row in db.execute(_primary_rows(run_id)).scalars().all():
        if row.workspace_id == workspace_id:
            continue
        if row.workspace_id is None:
            row.workspace_id = workspace_id
            row.owner_id = owner_id
            attached += 1
            continue
        copy_id = _copied_edge_id(row.id, workspace_id)
        if db.get(PaperRelationshipORM, copy_id) is not None:
            continue
        db.add(
            PaperRelationshipORM(
                id=copy_id,
                run_id=row.run_id,
                workspace_id=workspace_id,
                owner_id=owner_id,
                copied_from=row.id,
                source_paper_id=row.source_paper_id,
                target_paper_id=row.target_paper_id,
                relationship_type=row.relationship_type,
                detection_method=row.detection_method,
                rule_fired=row.rule_fired,
                llm_confirmed=row.llm_confirmed,
                evidence=list(row.evidence or []),
                supporting_references=list(row.supporting_references or []),
                confidence=row.confidence,
                confidence_basis=dict(row.confidence_basis or {}),
                user_state=UserState.PENDING.value,
                created_at=datetime.now(timezone.utc),
            )
        )
        attached += 1
    db.commit()
    return attached


def get_workspace_trail_edges(db: Session, workspace_id: str) -> list[TrailEdge]:
    rows = (
        db.execute(
            select(PaperRelationshipORM)
            .where(PaperRelationshipORM.workspace_id == workspace_id)
            .order_by(PaperRelationshipORM.target_paper_id, PaperRelationshipORM.relationship_type)
        )
        .scalars()
        .all()
    )
    return [_trail_edge_domain_from_orm(r) for r in rows]


def accept_reject_workspace_edge(
    db: Session, workspace_id: str, owner_id: str, edge_id: str, state: UserState
) -> TrailEdge | None:
    row = db.get(PaperRelationshipORM, edge_id)
    if row is None or row.workspace_id != workspace_id or (row.owner_id not in (None, owner_id)):
        return None
    row.user_state = state.value
    db.commit()
    db.refresh(row)
    return _trail_edge_domain_from_orm(row)


# ---------------------------------------------------------------------------
# RAG + citations (Phase 9): chat sessions/messages, claims, citations
# ---------------------------------------------------------------------------


def _chat_session_from_orm(row: ChatSessionORM) -> ChatSession:
    return ChatSession(
        session_id=row.id,
        workspace_id=row.workspace_id,
        owner_id=row.owner_id,
        title=row.title,
        created_at=row.created_at,
    )


def _chat_message_from_orm(row: ChatMessageORM) -> ChatMessage:
    return ChatMessage(
        message_id=row.id,
        session_id=row.session_id,
        role=ChatRole(row.role),
        content=row.content,
        citations=list(row.citations or []),
        tokens_prompt=row.tokens_prompt,
        tokens_completion=row.tokens_completion,
        faithfulness=row.faithfulness,
        answerable=row.answerable,
        suggestion=row.suggestion,
        unsupported_dropped=row.unsupported_dropped or 0,
        warnings=list(row.warnings or []),
        created_at=row.created_at,
    )


def create_chat_session(db: Session, session: ChatSession) -> ChatSession:
    db.add(
        ChatSessionORM(
            id=session.session_id,
            workspace_id=session.workspace_id,
            owner_id=session.owner_id,
            title=session.title,
        )
    )
    db.commit()
    row = db.get(ChatSessionORM, session.session_id)
    assert row is not None
    return _chat_session_from_orm(row)


def get_chat_session(db: Session, session_id: str, *, workspace_id: str, owner_id: str) -> ChatSession | None:
    row = db.get(ChatSessionORM, session_id)
    if row is None or row.workspace_id != workspace_id or row.owner_id != owner_id:
        return None
    return _chat_session_from_orm(row)


def list_chat_sessions(db: Session, workspace_id: str, owner_id: str) -> list[ChatSession]:
    rows = (
        db.execute(
            select(ChatSessionORM)
            .where(ChatSessionORM.workspace_id == workspace_id, ChatSessionORM.owner_id == owner_id)
            .order_by(ChatSessionORM.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_chat_session_from_orm(r) for r in rows]


def add_chat_message(db: Session, message: ChatMessage) -> ChatMessage:
    db.add(
        ChatMessageORM(
            id=message.message_id,
            session_id=message.session_id,
            role=message.role.value,
            content=message.content,
            citations=list(message.citations),
            tokens_prompt=message.tokens_prompt,
            tokens_completion=message.tokens_completion,
            faithfulness=message.faithfulness,
            answerable=message.answerable,
            suggestion=message.suggestion,
            unsupported_dropped=message.unsupported_dropped,
            warnings=list(message.warnings),
        )
    )
    db.commit()
    row = db.get(ChatMessageORM, message.message_id)
    assert row is not None
    return _chat_message_from_orm(row)


def delete_chat_message(db: Session, message_id: str) -> None:
    """Remove one message and the claims that grounded it (a regenerated answer)."""
    for claim in db.execute(select(ClaimORM).where(ClaimORM.artefact_id == message_id)).scalars().all():
        db.delete(claim)
    row = db.get(ChatMessageORM, message_id)
    if row is not None:
        db.delete(row)
    db.commit()


def get_chat_messages(db: Session, session_id: str) -> list[ChatMessage]:
    rows = (
        db.execute(
            select(ChatMessageORM)
            .where(ChatMessageORM.session_id == session_id)
            .order_by(ChatMessageORM.created_at, ChatMessageORM.id)
        )
        .scalars()
        .all()
    )
    return [_chat_message_from_orm(r) for r in rows]


def _claim_from_orm(row: ClaimORM) -> Claim:
    return Claim(
        claim_id=row.id,
        workspace_id=row.workspace_id,
        artefact_kind=row.artefact_kind,
        artefact_id=row.artefact_id,
        sentence=row.sentence,
        supporting_chunk_ids=list(row.supporting_chunk_ids or []),
        supporting_paper_ids=list(row.supporting_paper_ids or []),
        is_supported=row.is_supported,
        citation_precision=row.citation_precision,
        citation_recall=row.citation_recall,
    )


def save_claims(db: Session, claims: list[Claim]) -> None:
    for c in claims:
        existing = db.get(ClaimORM, c.claim_id)
        payload = dict(
            workspace_id=c.workspace_id,
            artefact_kind=c.artefact_kind,
            artefact_id=c.artefact_id,
            sentence=c.sentence,
            supporting_chunk_ids=list(c.supporting_chunk_ids),
            supporting_paper_ids=list(c.supporting_paper_ids),
            is_supported=c.is_supported,
            citation_precision=c.citation_precision,
            citation_recall=c.citation_recall,
        )
        if existing is None:
            db.add(ClaimORM(id=c.claim_id, **payload))
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
    db.commit()


def _claim_order(claim_id: str) -> tuple[str, int]:
    """Claim ids end in the sentence's index (`clm_<artefact>_<i>`); order by
    that number, so an answer's 10th sentence never sorts before its 2nd."""
    head, _, tail = claim_id.rpartition("_")
    return (head, int(tail)) if tail.isdigit() else (claim_id, -1)


def get_claims_for_artefact(db: Session, artefact_id: str) -> list[Claim]:
    rows = db.execute(select(ClaimORM).where(ClaimORM.artefact_id == artefact_id)).scalars().all()
    return [_claim_from_orm(r) for r in sorted(rows, key=lambda r: _claim_order(r.id))]


def _citation_from_orm(row: CitationORM) -> Citation:
    return Citation(
        citation_id=row.id,
        workspace_id=row.workspace_id,
        paper_id=row.paper_id,
        csl_json=dict(row.csl_json or {}),
        formatted=dict(row.formatted or {}),
        resolved_from=row.resolved_from,
    )


def upsert_citation(db: Session, citation: Citation, *, owner_id: str | None = None) -> Citation:
    row = db.execute(
        select(CitationORM).where(
            CitationORM.workspace_id == citation.workspace_id, CitationORM.paper_id == citation.paper_id
        )
    ).scalar_one_or_none()
    if row is None:
        row = CitationORM(id=citation.citation_id, workspace_id=citation.workspace_id, paper_id=citation.paper_id)
        db.add(row)
    row.owner_id = owner_id
    row.csl_json = citation.csl_json
    row.formatted = citation.formatted
    row.resolved_from = citation.resolved_from
    db.commit()
    db.refresh(row)
    return _citation_from_orm(row)


def get_citations(db: Session, workspace_id: str) -> list[Citation]:
    rows = (
        db.execute(select(CitationORM).where(CitationORM.workspace_id == workspace_id).order_by(CitationORM.paper_id))
        .scalars()
        .all()
    )
    return [_citation_from_orm(r) for r in rows]


# ---------------------------------------------------------------------------
# Comparison (Phase 10): comparisons + workspaces.comparison_schema
# ---------------------------------------------------------------------------


def _comparison_from_orm(row: ComparisonORM) -> Comparison:
    return Comparison(
        comparison_id=row.id,
        workspace_id=row.workspace_id,
        column_schema=ComparisonSchema.model_validate(row.schema_json or {"columns": []}),
        paper_ids=list(row.paper_ids or []),
        rows=[ComparisonRow.model_validate(r) for r in (row.rows_json or [])],
        coverage=row.coverage,
        decontext_eval=row.decontext_eval,
        created_at=row.created_at,
    )


def save_comparison(db: Session, comparison: Comparison, *, owner_id: str | None = None) -> Comparison:
    row = db.get(ComparisonORM, comparison.comparison_id)
    payload = dict(
        workspace_id=comparison.workspace_id,
        owner_id=owner_id,
        schema_json=comparison.column_schema.model_dump(mode="json"),
        paper_ids=list(comparison.paper_ids),
        rows_json=[r.model_dump(mode="json") for r in comparison.rows],
        coverage=comparison.coverage,
        decontext_eval=comparison.decontext_eval,
    )
    if row is None:
        db.add(ComparisonORM(id=comparison.comparison_id, created_at=comparison.created_at, **payload))
    else:
        for k, v in payload.items():
            setattr(row, k, v)
    db.commit()
    stored = db.get(ComparisonORM, comparison.comparison_id)
    assert stored is not None
    return _comparison_from_orm(stored)


def get_comparison(db: Session, comparison_id: str, *, workspace_id: str) -> Comparison | None:
    row = db.get(ComparisonORM, comparison_id)
    if row is None or row.workspace_id != workspace_id:
        return None
    return _comparison_from_orm(row)


def list_comparisons(db: Session, workspace_id: str) -> list[Comparison]:
    rows = (
        db.execute(
            select(ComparisonORM)
            .where(ComparisonORM.workspace_id == workspace_id)
            .order_by(ComparisonORM.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_comparison_from_orm(r) for r in rows]


def set_workspace_comparison_schema(
    db: Session, workspace_id: str, owner_id: str, schema: ComparisonSchema
) -> None:
    row = _owned_workspace_row(db, workspace_id, owner_id)
    if row is None:
        return
    row.comparison_schema = schema.model_dump(mode="json")
    db.commit()


# ---------------------------------------------------------------------------
# Research gaps (Phase 11): research_gaps, workspace-scoped
# ---------------------------------------------------------------------------


def _gap_from_orm(row: ResearchGapORM) -> ResearchGap:
    return ResearchGap(
        gap_id=row.id,
        workspace_id=row.workspace_id,
        statement=row.statement,
        gap_type=GapType(row.gap_type),
        supporting_papers=list(row.supporting_papers or []),
        supporting_evidence=[GapEvidence.model_validate(e) for e in (row.supporting_evidence or [])],
        conflicting_evidence=[GapEvidence.model_validate(e) for e in (row.conflicting_evidence or [])],
        why_unaddressed=row.why_unaddressed,
        affected_methods=list(row.affected_methods or []),
        affected_datasets=list(row.affected_datasets or []),
        evidence_coverage=row.evidence_coverage,
        novelty_assessment=row.novelty_assessment,
        confidence=Confidence(row.confidence),
        confidence_basis=dict(row.confidence_basis or {}),
        proposed_direction=row.proposed_direction,
        detection_rule=row.detection_rule,
        self_support_passed=row.self_support_passed,
        user_state=row.user_state,
        generated_at=row.generated_at,
        generator_model=row.generator_model,
        match_key=row.match_key,
    )


def save_gaps(db: Session, workspace_id: str, gaps: list[ResearchGap], *, owner_id: str | None = None) -> None:
    """Replace this workspace's candidate gaps. Rows a user has `accepted` or
    `rejected` are kept untouched -- a rerun never clobbers a human decision
    (and the pipeline already skips a `rejected` gap_id) -- and so is a gap any
    direction rests on: deleting it would cascade to those directions,
    accepted ones included."""
    keep_ids = {g.gap_id for g in gaps}
    directed = set(
        db.execute(select(ResearchDirectionORM.gap_id).where(ResearchDirectionORM.workspace_id == workspace_id)).scalars().all()
    )
    for row in db.execute(select(ResearchGapORM).where(ResearchGapORM.workspace_id == workspace_id)).scalars().all():
        if row.user_state != GapUserState.CANDIDATE.value:
            continue
        if row.id not in keep_ids and row.id not in directed:
            db.delete(row)

    for gap in gaps:
        existing = db.get(ResearchGapORM, gap.gap_id)
        payload = dict(
            workspace_id=gap.workspace_id,
            owner_id=owner_id,
            statement=gap.statement,
            gap_type=gap.gap_type.value,
            supporting_papers=list(gap.supporting_papers),
            supporting_evidence=[e.model_dump(mode="json") for e in gap.supporting_evidence],
            conflicting_evidence=[e.model_dump(mode="json") for e in gap.conflicting_evidence],
            why_unaddressed=gap.why_unaddressed,
            affected_methods=list(gap.affected_methods),
            affected_datasets=list(gap.affected_datasets),
            evidence_coverage=gap.evidence_coverage,
            novelty_assessment=gap.novelty_assessment,
            confidence=gap.confidence.value,
            confidence_basis=gap.confidence_basis,
            proposed_direction=gap.proposed_direction,
            detection_rule=gap.detection_rule,
            self_support_passed=gap.self_support_passed,
            generator_model=gap.generator_model,
            match_key=gap.match_key,
        )
        if existing is None:
            db.add(ResearchGapORM(id=gap.gap_id, user_state=gap.user_state, generated_at=gap.generated_at, **payload))
        elif existing.user_state == GapUserState.CANDIDATE.value:
            for k, v in payload.items():
                setattr(existing, k, v)
    db.commit()


def get_gaps(db: Session, workspace_id: str, *, state: str | None = None) -> list[ResearchGap]:
    stmt = select(ResearchGapORM).where(ResearchGapORM.workspace_id == workspace_id)
    if state is not None:
        stmt = stmt.where(ResearchGapORM.user_state == state)
    rows = db.execute(stmt.order_by(ResearchGapORM.gap_type, ResearchGapORM.id)).scalars().all()
    return [_gap_from_orm(r) for r in rows]


def get_gap(db: Session, gap_id: str, *, workspace_id: str) -> ResearchGap | None:
    row = db.get(ResearchGapORM, gap_id)
    if row is None or row.workspace_id != workspace_id:
        return None
    return _gap_from_orm(row)


@dataclass(frozen=True)
class DecidedGaps:
    """The gaps a person has decided on, by id and by what they say."""

    accepted_ids: frozenset[str]
    accepted_keys: frozenset[str]
    rejected_ids: frozenset[str]
    rejected_keys: frozenset[str]

    def rejected(self, gap_id: str, match_key: str) -> bool:
        return gap_id in self.rejected_ids or match_key in self.rejected_keys

    def accepted(self, gap_id: str, match_key: str) -> bool:
        return gap_id in self.accepted_ids or match_key in self.accepted_keys


def get_decided_gaps(db: Session, workspace_id: str) -> DecidedGaps:
    rows = db.execute(
        select(ResearchGapORM.id, ResearchGapORM.match_key, ResearchGapORM.user_state).where(
            ResearchGapORM.workspace_id == workspace_id,
            ResearchGapORM.user_state != GapUserState.CANDIDATE.value,
        )
    ).all()

    def pick(state: GapUserState, col: int) -> frozenset[str]:
        return frozenset(v for r in rows if r[2] == state.value and (v := r[col]))

    return DecidedGaps(
        accepted_ids=pick(GapUserState.ACCEPTED, 0),
        accepted_keys=pick(GapUserState.ACCEPTED, 1),
        rejected_ids=pick(GapUserState.REJECTED, 0),
        rejected_keys=pick(GapUserState.REJECTED, 1),
    )


def get_rejected_gap_ids(db: Session, workspace_id: str) -> set[str]:
    rows = db.execute(
        select(ResearchGapORM.id).where(
            ResearchGapORM.workspace_id == workspace_id,
            ResearchGapORM.user_state == GapUserState.REJECTED.value,
        )
    ).all()
    return {r[0] for r in rows}


def set_gap_user_state(
    db: Session, gap_id: str, *, workspace_id: str, owner_id: str, state: GapUserState
) -> ResearchGap | None:
    row = db.get(ResearchGapORM, gap_id)
    if row is None or row.workspace_id != workspace_id or (row.owner_id not in (None, owner_id)):
        return None
    row.user_state = state.value
    db.commit()
    db.refresh(row)
    return _gap_from_orm(row)


# ---------------------------------------------------------------------------
# Research directions (Phase 12): research_directions, workspace-scoped
# ---------------------------------------------------------------------------


def _direction_from_orm(row: ResearchDirectionORM) -> ResearchDirection:
    return ResearchDirection(
        direction_id=row.id,
        workspace_id=row.workspace_id,
        gap_id=row.gap_id,
        proposal=row.proposal,
        motivation=row.motivation,
        supporting_evidence=[GapEvidence.model_validate(e) for e in (row.supporting_evidence or [])],
        related_papers=list(row.related_papers or []),
        suggested_method=row.suggested_method,
        possible_dataset=row.possible_dataset,
        evaluation_strategy=row.evaluation_strategy,
        risks=list(row.risks or []),
        kind=row.kind,
        critique=dict(row.critique or {}),
        confidence=Confidence(row.confidence),
        confidence_basis=dict(row.confidence_basis or {}),
        flags=list(row.flags or []),
        user_state=row.user_state,
        generated_at=row.generated_at,
        generator_model=row.generator_model,
    )


def save_directions(
    db: Session,
    workspace_id: str,
    directions: list[ResearchDirection],
    *,
    owner_id: str | None = None,
    gap_ids: Collection[str] | None = None,
) -> None:
    """Replace the candidate directions of the gaps this run regenerated
    (`gap_ids`; every gap in the workspace when omitted). Directions are
    generated per chosen gap, so another gap's unreviewed directions are left
    alone, and rows a user has `accepted` or `rejected` are kept untouched --
    a rerun never clobbers a human decision."""
    keep_ids = {d.direction_id for d in directions}
    regenerated = None if gap_ids is None else set(gap_ids)
    for row in (
        db.execute(select(ResearchDirectionORM).where(ResearchDirectionORM.workspace_id == workspace_id))
        .scalars()
        .all()
    ):
        if row.user_state != DirectionUserState.CANDIDATE.value:
            continue
        if regenerated is not None and row.gap_id not in regenerated:
            continue
        if row.id not in keep_ids:
            db.delete(row)

    for d in directions:
        existing = db.get(ResearchDirectionORM, d.direction_id)
        payload = dict(
            workspace_id=d.workspace_id,
            owner_id=owner_id,
            gap_id=d.gap_id,
            proposal=d.proposal,
            motivation=d.motivation,
            supporting_evidence=[e.model_dump(mode="json") for e in d.supporting_evidence],
            related_papers=list(d.related_papers),
            suggested_method=d.suggested_method,
            possible_dataset=d.possible_dataset,
            evaluation_strategy=d.evaluation_strategy,
            risks=list(d.risks),
            kind=d.kind,
            critique=d.critique,
            confidence=d.confidence.value,
            confidence_basis=d.confidence_basis,
            flags=list(d.flags),
            generator_model=d.generator_model,
        )
        if existing is None:
            db.add(ResearchDirectionORM(id=d.direction_id, user_state=d.user_state, generated_at=d.generated_at, **payload))
        elif existing.user_state == DirectionUserState.CANDIDATE.value:
            for k, v in payload.items():
                setattr(existing, k, v)
    db.commit()


def get_directions(db: Session, workspace_id: str, *, state: str | None = None, gap_id: str | None = None) -> list[ResearchDirection]:
    stmt = select(ResearchDirectionORM).where(ResearchDirectionORM.workspace_id == workspace_id)
    if state is not None:
        stmt = stmt.where(ResearchDirectionORM.user_state == state)
    if gap_id is not None:
        stmt = stmt.where(ResearchDirectionORM.gap_id == gap_id)
    rows = db.execute(stmt.order_by(ResearchDirectionORM.gap_id, ResearchDirectionORM.id)).scalars().all()
    return [_direction_from_orm(r) for r in rows]


def get_direction(db: Session, direction_id: str, *, workspace_id: str) -> ResearchDirection | None:
    row = db.get(ResearchDirectionORM, direction_id)
    if row is None or row.workspace_id != workspace_id:
        return None
    return _direction_from_orm(row)


def set_direction_user_state(
    db: Session, direction_id: str, *, workspace_id: str, owner_id: str, state: DirectionUserState
) -> ResearchDirection | None:
    row = db.get(ResearchDirectionORM, direction_id)
    if row is None or row.workspace_id != workspace_id or (row.owner_id not in (None, owner_id)):
        return None
    row.user_state = state.value
    db.commit()
    db.refresh(row)
    return _direction_from_orm(row)


# ---------------------------------------------------------------------------
# Research graph (Phase 13): workspaces.graph_json
# ---------------------------------------------------------------------------


def set_workspace_graph(db: Session, workspace_id: str, owner_id: str, graph: ResearchGraph) -> None:
    row = _owned_workspace_row(db, workspace_id, owner_id)
    if row is None:
        return
    row.graph_json = graph.model_dump(mode="json")
    db.commit()


def get_workspace_graph(db: Session, workspace_id: str, owner_id: str) -> ResearchGraph | None:
    row = _owned_workspace_row(db, workspace_id, owner_id)
    if row is None or row.graph_json is None:
        return None
    return ResearchGraph.model_validate(row.graph_json)


def mark_extra_citation_hop(db: Session, run_id: str) -> None:
    """Records the orchestrator's bounded "one extra citation hop"
    decision (Architecture §4) on the run it was authorised for."""
    row = db.get(SearchRunORM, run_id)
    if row is None:
        return
    row.extra_citation_hop_used = True
    db.commit()


# ---------------------------------------------------------------------------
# Orchestrator (Phase 14): stage_runs -- the ToolLog append-only tool-call log
# ---------------------------------------------------------------------------


def _stage_run_from_orm(row: StageRunORM) -> StageRun:
    return StageRun(
        id=row.id,
        owner_id=row.owner_id,
        workspace_id=row.workspace_id,
        job_id=row.job_id,
        stage=StageName(row.stage),
        tool=row.tool,
        input_hash=row.input_hash,
        output_hash=row.output_hash,
        tokens_prompt=row.tokens_prompt,
        tokens_completion=row.tokens_completion,
        latency_ms=row.latency_ms,
        ok=row.ok,
        error=row.error,
        ts=row.ts,
    )


def record_stage_run(db: Session, run: StageRun) -> StageRun:
    db.add(
        StageRunORM(
            id=run.id,
            owner_id=run.owner_id,
            workspace_id=run.workspace_id,
            job_id=run.job_id,
            stage=run.stage.value,
            tool=run.tool,
            input_hash=run.input_hash,
            output_hash=run.output_hash,
            tokens_prompt=run.tokens_prompt,
            tokens_completion=run.tokens_completion,
            latency_ms=run.latency_ms,
            ok=run.ok,
            error=run.error,
            ts=run.ts,
        )
    )
    db.commit()
    return run


def list_stage_runs(
    db: Session, workspace_id: str, *, stage: StageName | None = None, limit: int = 50
) -> list[StageRun]:
    stmt = select(StageRunORM).where(StageRunORM.workspace_id == workspace_id)
    if stage is not None:
        stmt = stmt.where(StageRunORM.stage == stage.value)
    stmt = stmt.order_by(StageRunORM.ts.desc(), StageRunORM.id.desc()).limit(limit)
    rows = db.execute(stmt).scalars().all()
    return [_stage_run_from_orm(r) for r in rows]


# ---------------------------------------------------------------------------
# Model-provider usage (remediation Phase 2)
# ---------------------------------------------------------------------------


def record_llm_call(db: Session, call: LlmCall) -> None:
    db.add(LlmCallORM(**call.model_dump()))
    db.commit()


def list_llm_calls(db: Session, owner_id: str, *, workspace_id: str | None = None) -> list[LlmCall]:
    stmt = select(LlmCallORM).where(LlmCallORM.owner_id == owner_id)
    if workspace_id is not None:
        stmt = stmt.where(LlmCallORM.workspace_id == workspace_id)
    rows = db.execute(stmt.order_by(LlmCallORM.created_at, LlmCallORM.id)).scalars().all()
    return [
        LlmCall(
            id=r.id, owner_id=r.owner_id, workspace_id=r.workspace_id, job_id=r.job_id, feature=r.feature,
            provider=r.provider, model=r.model, prompt_tokens=r.prompt_tokens, completion_tokens=r.completion_tokens,
            cached_prompt_tokens=r.cached_prompt_tokens, reasoning_tokens=r.reasoning_tokens, latency_ms=r.latency_ms,
            ok=r.ok, error_kind=r.error_kind, created_at=r.created_at,
        )
        for r in rows
    ]


@dataclass(frozen=True)
class UsageTotals:
    """Provider-reported usage summed over some of one user's `llm_calls`."""

    calls: int = 0
    failed_calls: int = 0
    # answered calls the provider sent no usage for: their tokens are unknown, not zero
    unreported_calls: int = 0
    prompt_tokens: int = 0
    cached_prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    first_at: datetime | None = None
    last_at: datetime | None = None


_USAGE_GROUPS = {
    "feature": LlmCallORM.feature,
    "provider": LlmCallORM.provider,
    "model": LlmCallORM.model,
    "workspace_id": LlmCallORM.workspace_id,
}


def summarize_llm_calls(
    db: Session,
    owner_id: str,
    *,
    since: datetime | None = None,
    workspace_id: str | None = None,
    by: tuple[str, ...] = (),
) -> list[tuple[tuple[str | None, ...], UsageTotals]]:
    """One user's usage since `since` (all of it if None), in one workspace
    or all, grouped by any of feature / provider / model / workspace_id --
    or a single total when `by` is empty (a total of nothing is all zeros)."""
    keys = [_USAGE_GROUPS[k] for k in by]
    c = LlmCallORM
    # an answered call can't have used no tokens at all: its provider didn't say
    no_usage = and_(c.ok.is_(True), c.prompt_tokens == 0, c.completion_tokens == 0)

    def total(expr: ColumnElement[int] | InstrumentedAttribute[int]) -> ColumnElement[int]:
        return func.coalesce(func.sum(expr), 0)

    stmt = select(
        *keys,
        func.count(c.id),
        total(case((c.ok.is_(False), 1), else_=0)),
        total(case((no_usage, 1), else_=0)),
        total(c.prompt_tokens),
        total(c.cached_prompt_tokens),
        total(c.completion_tokens),
        total(c.reasoning_tokens),
        func.min(c.created_at),
        func.max(c.created_at),
    ).where(c.owner_id == owner_id)
    if since is not None:
        stmt = stmt.where(c.created_at >= since)
    if workspace_id is not None:
        stmt = stmt.where(c.workspace_id == workspace_id)
    if keys:
        stmt = stmt.group_by(*keys)
    out: list[tuple[tuple[str | None, ...], UsageTotals]] = []
    n = len(keys)
    for row in db.execute(stmt).all():
        values = tuple(row)
        calls, failed, unreported, prompt, cached, completion, reasoning = (int(v) for v in values[n : n + 7])
        out.append(
            (
                values[:n],
                UsageTotals(
                    calls=calls,
                    failed_calls=failed,
                    unreported_calls=unreported,
                    prompt_tokens=prompt,
                    cached_prompt_tokens=cached,
                    completion_tokens=completion,
                    reasoning_tokens=reasoning,
                    first_at=values[n + 7],
                    last_at=values[n + 8],
                ),
            )
        )
    return out


def workspace_titles(db: Session, owner_id: str, workspace_ids: list[str]) -> dict[str, str]:
    """Titles of the owner's workspaces among `workspace_ids` (a deleted one is absent)."""
    if not workspace_ids:
        return {}
    rows = db.execute(
        select(WorkspaceORM.id, WorkspaceORM.title).where(
            WorkspaceORM.owner_id == owner_id, WorkspaceORM.id.in_(workspace_ids)
        )
    ).all()
    return {r[0]: r[1] for r in rows}

