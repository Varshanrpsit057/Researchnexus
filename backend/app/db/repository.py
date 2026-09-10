"""Persistence mapping between domain (Pydantic) models and ORM rows.

Keeps app/services/ingest/* free of SQLAlchemy imports -- the pipeline
builds domain objects, and this module is the only place that knows how
they are stored (Architecture §2: deterministic storage code is its own
concern, separate from parsing logic).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    ApiKeyORM,
    JobORM,
    PaperChunkORM,
    PaperORM,
    RankedPaperORM,
    ResearchProfileORM,
    SearchCandidateORM,
    SearchRunORM,
    UserORM,
)
from app.domain.candidate import (
    CitationRelationship,
    DiscoveryStrategy,
    NormalizedCandidate,
    PaperCandidate,
    SearchRun,
)
from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.jobs import Job, JobKind, JobStatus
from app.domain.paper import ParsedDocument
from app.domain.profile import Confidence, ResearchProfile
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.domain.user import ApiKeyRecord, ApiKeyStatus, LlmProvider, User
from app.security.pdf_sanitizer import PdfFileMeta

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
    rows = db.execute(select(ApiKeyORM).where(ApiKeyORM.owner_id == owner_id)).scalars().all()
    return [_api_key_record_from_orm(r) for r in rows]


def has_working_api_key(db: Session, owner_id: str) -> bool:
    row = db.execute(
        select(ApiKeyORM).where(ApiKeyORM.owner_id == owner_id, ApiKeyORM.status == ApiKeyStatus.WORKING.value)
    ).first()
    return row is not None


def delete_api_key(db: Session, owner_id: str, provider: LlmProvider) -> bool:
    row = db.execute(
        select(ApiKeyORM).where(ApiKeyORM.owner_id == owner_id, ApiKeyORM.provider == provider.value)
    ).scalar_one_or_none()
    if row is None:
        return False
    db.delete(row)
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


# ---------------------------------------------------------------------------
# ResearchProfile
# ---------------------------------------------------------------------------


def _profile_domain_from_orm(row: ResearchProfileORM) -> ResearchProfile:
    return ResearchProfile.model_validate(row.profile_json)


def upsert_profile(db: Session, profile: ResearchProfile) -> ResearchProfile:
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
    db.commit()
    db.refresh(row)
    return _profile_domain_from_orm(row)


def get_profile(db: Session, paper_id: str, workspace_id: str | None = None) -> ResearchProfile | None:
    workspace_clause = (
        ResearchProfileORM.workspace_id.is_(None) if workspace_id is None else ResearchProfileORM.workspace_id == workspace_id
    )
    row = db.execute(
        select(ResearchProfileORM).where(ResearchProfileORM.paper_id == paper_id, workspace_clause)
    ).scalar_one_or_none()
    return _profile_domain_from_orm(row) if row else None


# ---------------------------------------------------------------------------
# Academic search (Phase 4): discovered papers + search runs + candidates
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def upsert_discovered_paper(db: Session, cand: NormalizedCandidate) -> str:
    """Link a normalised candidate to the global `papers` table, deduping by
    DOI -> versionless arXiv id -> normalised-title hash (Architecture §2).
    A new row is `source="discovery"`, `has_full_text=False`; an existing
    row only has its *empty* fields filled, never its richer data
    overwritten."""
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
    db.commit()
    db.refresh(row)
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
        tokens_prompt=row.tokens_prompt,
        tokens_completion=row.tokens_completion,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def create_search_run(db: Session, run: SearchRun) -> SearchRun:
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
        )
    )
    db.commit()
    return run


def get_search_run(db: Session, run_id: str) -> SearchRun | None:
    row = db.get(SearchRunORM, run_id)
    return _search_run_domain_from_orm(row) if row else None


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
