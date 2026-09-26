"""Assembles the final validated `ResearchProfile` from (a) the deterministic
bibliographic data already on the Paper row, (b) the LLM's extracted
understanding fields once every field has been through provenance_check.py,
and (c) the deterministically computed `extraction_confidence`. Also builds
the degraded fallback profile used when extraction fails outright (Data
Model §2: "On any ValidationError after the single repair retry -> ...")
and applies a user's `PATCH .../profile` edits (API spec §4).
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.paper import Section
from app.domain.profile import (
    Confidence,
    ProfileField,
    ProfileList,
    ProvenanceStatus,
    ResearchProfile,
    TokenUsage,
)
from app.llm.prompts.profile_v1 import ProfileExtraction
from app.services.profile.confidence import compute_extraction_confidence
from app.services.profile.provenance_check import resolve_field, resolve_list

_ABSTRACT_FALLBACK_CHARS = 600
_MAX_CANDIDATE_QUERIES = 25


def reconstruct_abstract(chunks: list[PaperChunk]) -> tuple[str, bool]:
    """Returns `(abstract_text, was_explicit_abstract_section)`. Phase 2
    never persists raw `full_text` -- `PaperChunk.text` is the only place
    the paper's own words survive, so the abstract is reconstructed from
    ABSTRACT-kind chunks (see app/services/ingest/chunker.py) rather than
    re-parsed from the PDF."""
    abstract_chunks = sorted((c for c in chunks if c.kind == ChunkKind.ABSTRACT), key=lambda c: c.char_start)
    if abstract_chunks:
        return " ".join(c.text.strip() for c in abstract_chunks), True

    body_chunks = sorted((c for c in chunks if c.kind == ChunkKind.BODY), key=lambda c: c.char_start)
    if body_chunks:
        return body_chunks[0].text.strip()[:_ABSTRACT_FALLBACK_CHARS], False
    return "(no extractable text)", False


def build_profile(
    *,
    profile_id: str,
    paper_id: str,
    title: str,
    authors: list[str],
    year: int | None,
    venue: str | None,
    doi: str | None,
    arxiv_id: str | None,
    chunks: list[PaperChunk],
    sections: list[Section],
    extraction: ProfileExtraction,
    extraction_model: str,
    tokens: TokenUsage,
    grounding: str = "full_text",
) -> tuple[ResearchProfile, list[str]]:
    abstract, has_explicit_abstract = reconstruct_abstract(chunks)
    warnings = [] if has_explicit_abstract else ["no_abstract_section_detected"]

    domain = resolve_field(paper_id, extraction.domain, chunks)
    research_problem = resolve_field(paper_id, extraction.research_problem, chunks)
    subdomains = resolve_list(paper_id, extraction.subdomains, chunks)
    research_questions = resolve_list(paper_id, extraction.research_questions, chunks)
    objectives = resolve_list(paper_id, extraction.objectives, chunks)
    methods = resolve_list(paper_id, extraction.methods, chunks)
    models = resolve_list(paper_id, extraction.models, chunks)
    algorithms = resolve_list(paper_id, extraction.algorithms, chunks)
    datasets = resolve_list(paper_id, extraction.datasets, chunks)
    evaluation_metrics = resolve_list(paper_id, extraction.evaluation_metrics, chunks)
    findings = resolve_list(paper_id, extraction.findings, chunks)
    limitations = resolve_list(paper_id, extraction.limitations, chunks)
    future_work = resolve_list(paper_id, extraction.future_work, chunks)
    important_entities = resolve_list(paper_id, extraction.important_entities, chunks)
    cited_methods = resolve_list(paper_id, extraction.cited_methods, chunks)

    list_fields = (
        subdomains, research_questions, objectives, methods, models, algorithms, datasets,
        evaluation_metrics, findings, limitations, future_work, important_entities, cited_methods,
    )
    all_fields = [domain, research_problem, *(f for lst in list_fields for f in lst.items)]
    confidence = compute_extraction_confidence(all_fields, sections)

    profile = ResearchProfile(
        profile_id=profile_id,
        paper_id=paper_id,
        grounding=grounding,
        title=title,
        abstract=abstract,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        domain=domain,
        subdomains=subdomains,
        research_problem=research_problem,
        research_questions=research_questions,
        objectives=objectives,
        keywords=extraction.keywords,
        methods=methods,
        models=models,
        algorithms=algorithms,
        datasets=datasets,
        evaluation_metrics=evaluation_metrics,
        findings=findings,
        limitations=limitations,
        future_work=future_work,
        important_entities=important_entities,
        cited_methods=cited_methods,
        candidate_search_queries=extraction.candidate_search_queries[:_MAX_CANDIDATE_QUERIES],
        extraction_confidence=confidence,
        extraction_model=extraction_model,
        tokens=tokens,
    )
    return profile, warnings


def build_fallback_profile(
    *,
    profile_id: str,
    paper_id: str,
    title: str,
    authors: list[str],
    year: int | None,
    venue: str | None,
    doi: str | None,
    arxiv_id: str | None,
    chunks: list[PaperChunk],
) -> ResearchProfile:
    """Data Model §2: repair-retry exhausted -> bibliographic fields filled,
    understanding fields empty, extraction_confidence=low."""
    abstract, _ = reconstruct_abstract(chunks)
    empty_field = ProfileField(value="", source_span=None, status=ProvenanceStatus.UNVERIFIED)
    return ResearchProfile(
        profile_id=profile_id,
        paper_id=paper_id,
        grounding="full_text",
        title=title,
        abstract=abstract,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        domain=empty_field,
        research_problem=empty_field,
        extraction_confidence=Confidence.LOW,
        extraction_model=None,
    )


class ProfilePatchRequest(BaseModel):
    """API spec §4 `PATCH .../profile` body: "a partial ResearchProfile
    (field -> new value)". Plain values only -- a human editing the UI
    supplies text/lists, never a `source_span` (see apply_patch below,
    which is the only place a user edit becomes a `ProfileField`)."""

    domain: str | None = None
    research_problem: str | None = None
    subdomains: list[str] | None = None
    research_questions: list[str] | None = None
    objectives: list[str] | None = None
    keywords: list[str] | None = None
    methods: list[str] | None = None
    models: list[str] | None = None
    algorithms: list[str] | None = None
    datasets: list[str] | None = None
    evaluation_metrics: list[str] | None = None
    findings: list[str] | None = None
    limitations: list[str] | None = None
    future_work: list[str] | None = None
    important_entities: list[str] | None = None
    cited_methods: list[str] | None = None
    candidate_search_queries: list[str] | None = None


def _user_edited_list(values: list[str]) -> ProfileList:
    return ProfileList(items=[ProfileField(value=v, source_span=None, status=ProvenanceStatus.USER_EDITED) for v in values])


def apply_patch(
    profile: ResearchProfile,
    *,
    domain: str | None = None,
    research_problem: str | None = None,
    subdomains: list[str] | None = None,
    research_questions: list[str] | None = None,
    objectives: list[str] | None = None,
    keywords: list[str] | None = None,
    methods: list[str] | None = None,
    models: list[str] | None = None,
    algorithms: list[str] | None = None,
    datasets: list[str] | None = None,
    evaluation_metrics: list[str] | None = None,
    findings: list[str] | None = None,
    limitations: list[str] | None = None,
    future_work: list[str] | None = None,
    important_entities: list[str] | None = None,
    cited_methods: list[str] | None = None,
    candidate_search_queries: list[str] | None = None,
) -> ResearchProfile:
    """API spec §4 `PATCH .../profile`: "Marks touched fields
    status:'user_edited'." Untouched fields (left `None`) keep whatever
    provenance they already had."""
    updates: dict[str, object] = {}
    if domain is not None:
        updates["domain"] = ProfileField(value=domain, source_span=None, status=ProvenanceStatus.USER_EDITED)
    if research_problem is not None:
        updates["research_problem"] = ProfileField(
            value=research_problem, source_span=None, status=ProvenanceStatus.USER_EDITED
        )
    for field_name, new_values in (
        ("subdomains", subdomains),
        ("research_questions", research_questions),
        ("objectives", objectives),
        ("methods", methods),
        ("models", models),
        ("algorithms", algorithms),
        ("datasets", datasets),
        ("evaluation_metrics", evaluation_metrics),
        ("findings", findings),
        ("limitations", limitations),
        ("future_work", future_work),
        ("important_entities", important_entities),
        ("cited_methods", cited_methods),
    ):
        if new_values is not None:
            updates[field_name] = _user_edited_list(new_values)
    if keywords is not None:
        updates["keywords"] = keywords
    if candidate_search_queries is not None:
        updates["candidate_search_queries"] = candidate_search_queries[:_MAX_CANDIDATE_QUERIES]

    if not updates:
        return profile
    updates["updated_at"] = datetime.now(timezone.utc)
    return profile.model_copy(update=updates)
