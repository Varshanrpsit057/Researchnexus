from __future__ import annotations

from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.paper import Section
from app.domain.profile import Confidence, ProvenanceStatus, TokenUsage
from app.llm.prompts.profile_v1 import ExtractedField, ExtractedList, ProfileExtraction
from app.services.profile.validator import (
    apply_patch,
    build_fallback_profile,
    build_profile,
    reconstruct_abstract,
)


def _abstract_chunk() -> PaperChunk:
    return PaperChunk(
        chunk_id="chk_abs",
        paper_id="pap_1",
        section="Abstract",
        section_order=0,
        page=1,
        char_start=0,
        char_end=30,
        kind=ChunkKind.ABSTRACT,
        text="This paper studies X problem.",
        token_count=5,
    )


def _body_chunk() -> PaperChunk:
    return PaperChunk(
        chunk_id="chk_body",
        paper_id="pap_1",
        section="1 Introduction",
        section_order=1,
        page=1,
        char_start=100,
        char_end=140,
        kind=ChunkKind.BODY,
        text="We propose a novel method for X.",
        token_count=6,
    )


def _extraction() -> ProfileExtraction:
    return ProfileExtraction(
        domain=ExtractedField(value="NLP", quote="This paper studies X problem."),
        research_problem=ExtractedField(value="X problem", quote="This paper studies X problem."),
        methods=ExtractedList(items=[ExtractedField(value="novel method", quote="We propose a novel method for X.")]),
        keywords=["NLP", "nlp"],
        candidate_search_queries=["X problem nlp"],
    )


def _bibliographic() -> dict[str, object]:
    return dict(paper_id="pap_1", title="A Paper", authors=["A. Author"], year=2023, venue=None, doi=None, arxiv_id=None)


def test_reconstruct_abstract_from_abstract_kind_chunks() -> None:
    text, explicit = reconstruct_abstract([_abstract_chunk(), _body_chunk()])
    assert text == "This paper studies X problem."
    assert explicit is True


def test_reconstruct_abstract_falls_back_to_first_body_chunk() -> None:
    text, explicit = reconstruct_abstract([_body_chunk()])
    assert text.startswith("We propose a novel method for X.")
    assert explicit is False


def test_reconstruct_abstract_handles_no_chunks_at_all() -> None:
    text, explicit = reconstruct_abstract([])
    assert text
    assert explicit is False


def test_build_profile_resolves_provenance_and_computes_confidence() -> None:
    chunks = [_abstract_chunk(), _body_chunk()]
    sections = [
        Section(title="Abstract", order=0, char_start=0, char_end=30, page_start=1, page_end=1),
        Section(title="Limitations", order=1, char_start=100, char_end=140, page_start=1, page_end=1),
    ]
    profile, warnings = build_profile(
        profile_id="prof_1",
        chunks=chunks,
        sections=sections,
        extraction=_extraction(),
        extraction_model="groq:llama-3.1-8b-instant",
        tokens=TokenUsage(prompt=100, completion=50),
        **_bibliographic(),  # type: ignore[arg-type]
    )
    assert profile.domain.status == ProvenanceStatus.VERIFIED
    assert profile.research_problem.status == ProvenanceStatus.VERIFIED
    assert profile.methods.items[0].status == ProvenanceStatus.VERIFIED
    assert profile.keywords == ["nlp"]
    assert profile.tokens.prompt == 100
    assert profile.abstract == "This paper studies X problem."
    assert warnings == []
    # all resolvable fields verified + a Limitations section present -> high
    assert profile.extraction_confidence == Confidence.HIGH


def test_build_profile_warns_when_no_explicit_abstract_section() -> None:
    chunks = [_body_chunk()]
    sections = [Section(title="1 Introduction", order=0, char_start=100, char_end=140, page_start=1, page_end=1)]
    _profile, warnings = build_profile(
        profile_id="prof_1",
        chunks=chunks,
        sections=sections,
        extraction=ProfileExtraction(domain=ExtractedField(value="NLP"), research_problem=ExtractedField(value="X")),
        extraction_model="groq:llama-3.1-8b-instant",
        tokens=TokenUsage(),
        **_bibliographic(),  # type: ignore[arg-type]
    )
    assert "no_abstract_section_detected" in warnings


def test_build_fallback_profile_has_empty_understanding_fields_and_low_confidence() -> None:
    profile = build_fallback_profile(
        profile_id="prof_2", chunks=[_abstract_chunk()], **_bibliographic()  # type: ignore[arg-type]
    )
    assert profile.extraction_confidence == Confidence.LOW
    assert profile.domain.value == ""
    assert profile.research_problem.value == ""
    assert profile.methods.items == []
    assert profile.title == "A Paper"
    assert profile.abstract == "This paper studies X problem."


def test_apply_patch_marks_touched_fields_user_edited_and_leaves_others() -> None:
    chunks = [_abstract_chunk(), _body_chunk()]
    sections = [Section(title="Abstract", order=0, char_start=0, char_end=30, page_start=1, page_end=1)]
    profile, _warnings = build_profile(
        profile_id="prof_1", chunks=chunks, sections=sections, extraction=_extraction(),
        extraction_model="groq:x", tokens=TokenUsage(), **_bibliographic(),  # type: ignore[arg-type]
    )
    original_confidence = profile.extraction_confidence

    patched = apply_patch(profile, domain="Computer Vision", datasets=["ImageNet"])

    assert patched.domain.value == "Computer Vision"
    assert patched.domain.status == ProvenanceStatus.USER_EDITED
    assert patched.domain.source_span is None
    assert [d.value for d in patched.datasets.items] == ["ImageNet"]
    assert patched.datasets.items[0].status == ProvenanceStatus.USER_EDITED
    # untouched fields keep their original resolved provenance
    assert patched.research_problem.status == profile.research_problem.status
    assert patched.research_problem.value == profile.research_problem.value
    # a user edit doesn't change the original extraction's confidence score
    assert patched.extraction_confidence == original_confidence


def test_apply_patch_with_no_fields_returns_equivalent_profile() -> None:
    chunks = [_abstract_chunk()]
    sections = [Section(title="Abstract", order=0, char_start=0, char_end=30, page_start=1, page_end=1)]
    profile, _warnings = build_profile(
        profile_id="prof_1", chunks=chunks, sections=sections,
        extraction=ProfileExtraction(domain=ExtractedField(value="NLP"), research_problem=ExtractedField(value="X")),
        extraction_model="groq:x", tokens=TokenUsage(), **_bibliographic(),  # type: ignore[arg-type]
    )
    patched = apply_patch(profile)
    assert patched.domain.value == profile.domain.value
    assert patched.model_dump(exclude={"updated_at"}) == profile.model_dump(exclude={"updated_at"})
