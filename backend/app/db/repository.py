"""Persistence mapping between domain (Pydantic) models and ORM rows.

Keeps app/services/ingest/* free of SQLAlchemy imports -- the pipeline
builds domain objects, and this module is the only place that knows how
they are stored (Architecture §2: deterministic storage code is its own
concern, separate from parsing logic).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    ApiKeyORM,
    ChatMessageORM,
    ChatSessionORM,
    CitationORM,
    ClaimORM,
    ComparisonORM,
    JobORM,
    PaperChunkORM,
    PaperORM,
    PaperRelationshipORM,
    RankedPaperORM,
    ResearchDirectionORM,
    ResearchGapORM,
    ResearchProfileORM,
    SearchCandidateORM,
    SearchRunORM,
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
from app.domain.paper import ParsedDocument
from app.domain.profile import Confidence, ResearchProfile, TokenUsage
from app.domain.ranking import RankedPaper, RankingExplanation, SignalScores
from app.domain.trail import DetectionMethod, Evidence, RelationshipType, TrailEdge, UserState
from app.domain.user import ApiKeyRecord, ApiKeyStatus, LlmProvider, User
from app.domain.workspace import (
    AddedBy,
    Grounding,
    ResearchWorkspace,
    WorkspacePaper,
    WorkspacePaperRole,
)
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


def save_trail_edges(db: Session, run_id: str, edges: list[TrailEdge]) -> None:
    """Replace this run's non-rejected trail edges. Rows a user has
    `rejected` are kept untouched (the builder already skips those keys, so
    a rejected edge is never re-proposed on a re-run)."""
    keep_ids = {e.edge_id for e in edges}
    for row in db.execute(select(PaperRelationshipORM).where(PaperRelationshipORM.run_id == run_id)).scalars().all():
        if row.user_state == UserState.REJECTED.value:
            continue
        if row.id not in keep_ids:
            db.delete(row)

    for edge in edges:
        existing = db.get(PaperRelationshipORM, edge.edge_id)
        payload = dict(
            run_id=edge.run_id,
            workspace_id=edge.workspace_id,
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
            db.add(PaperRelationshipORM(id=edge.edge_id, user_state=edge.user_state, created_at=edge.created_at, **payload))
        elif existing.user_state != UserState.REJECTED.value:
            for key, value in payload.items():
                setattr(existing, key, value)
    db.commit()


def get_trail_edges(db: Session, run_id: str) -> list[TrailEdge]:
    rows = (
        db.execute(
            select(PaperRelationshipORM)
            .where(PaperRelationshipORM.run_id == run_id)
            .order_by(PaperRelationshipORM.target_paper_id, PaperRelationshipORM.relationship_type)
        )
        .scalars()
        .all()
    )
    return [_trail_edge_domain_from_orm(r) for r in rows]


def get_rejected_trail_keys(db: Session, run_id: str) -> set[tuple[str, str]]:
    rows = db.execute(
        select(PaperRelationshipORM.target_paper_id, PaperRelationshipORM.relationship_type).where(
            PaperRelationshipORM.run_id == run_id,
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
        token_budget_usd=row.token_budget_usd,
        tokens_used=TokenUsage(prompt=row.tokens_prompt, completion=row.tokens_completion),
        cost_used_usd=row.cost_usd,
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
            token_budget_usd=ws.token_budget_usd,
            tokens_prompt=ws.tokens_used.prompt,
            tokens_completion=ws.tokens_used.completion,
            cost_usd=ws.cost_used_usd,
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
    token_budget_usd: float | None = None,
) -> ResearchWorkspace | None:
    row = _owned_workspace_row(db, workspace_id, owner_id)
    if row is None:
        return None
    if title is not None:
        row.title = title
    if token_budget_usd is not None:
        row.token_budget_usd = token_budget_usd
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
    # cascade); release membership so orphaned trail rows do not point at a
    # dead workspace. The edges stay run-scoped.
    for edge in (
        db.execute(select(PaperRelationshipORM).where(PaperRelationshipORM.workspace_id == workspace_id))
        .scalars()
        .all()
    ):
        edge.workspace_id = None
        edge.owner_id = None
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
    papers = db.scalar(
        select(func.count())
        .select_from(WorkspacePaperORM)
        .where(WorkspacePaperORM.workspace_id == workspace_id)
    )
    edges = db.scalar(
        select(func.count())
        .select_from(PaperRelationshipORM)
        .where(
            PaperRelationshipORM.workspace_id == workspace_id,
            PaperRelationshipORM.user_state != UserState.REJECTED.value,
        )
    )
    # gaps / directions arrive in Phases 11 / 12
    return {"papers": int(papers or 0), "edges": int(edges or 0), "gaps": 0, "directions": 0}


def attach_run_edges_to_workspace(
    db: Session, *, run_id: str, workspace_id: str, owner_id: str
) -> int:
    """Stamp workspace_id / owner_id onto the Phase 7 trail rows for a run,
    making them the workspace trail (GET /workspaces/{id}/trail)."""
    rows = (
        db.execute(select(PaperRelationshipORM).where(PaperRelationshipORM.run_id == run_id))
        .scalars()
        .all()
    )
    for row in rows:
        row.workspace_id = workspace_id
        row.owner_id = owner_id
    db.commit()
    return len(rows)


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
        )
    )
    db.commit()
    row = db.get(ChatMessageORM, message.message_id)
    assert row is not None
    return _chat_message_from_orm(row)


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


def get_claims_for_artefact(db: Session, artefact_id: str) -> list[Claim]:
    rows = (
        db.execute(select(ClaimORM).where(ClaimORM.artefact_id == artefact_id).order_by(ClaimORM.id))
        .scalars()
        .all()
    )
    return [_claim_from_orm(r) for r in rows]


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
    )


def save_gaps(db: Session, workspace_id: str, gaps: list[ResearchGap], *, owner_id: str | None = None) -> None:
    """Replace this workspace's candidate gaps. Rows a user has `accepted` or
    `rejected` are kept untouched -- a rerun never clobbers a human decision
    (and the pipeline already skips a `rejected` gap_id)."""
    keep_ids = {g.gap_id for g in gaps}
    for row in db.execute(select(ResearchGapORM).where(ResearchGapORM.workspace_id == workspace_id)).scalars().all():
        if row.user_state != GapUserState.CANDIDATE.value:
            continue
        if row.id not in keep_ids:
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
    db: Session, workspace_id: str, directions: list[ResearchDirection], *, owner_id: str | None = None
) -> None:
    """Replace this workspace's candidate directions. Rows a user has
    `accepted` or `rejected` are kept untouched -- a rerun never clobbers a
    human decision."""
    keep_ids = {d.direction_id for d in directions}
    for row in (
        db.execute(select(ResearchDirectionORM).where(ResearchDirectionORM.workspace_id == workspace_id))
        .scalars()
        .all()
    ):
        if row.user_state != DirectionUserState.CANDIDATE.value:
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
