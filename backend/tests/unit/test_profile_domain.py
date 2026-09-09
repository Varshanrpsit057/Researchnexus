from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from app.domain.profile import (
    Confidence,
    ProfileField,
    ProfileList,
    ProvenanceStatus,
    ResearchProfile,
    SourceSpan,
    TokenUsage,
)


def _minimal_profile(**overrides: object) -> ResearchProfile:
    kwargs: dict[str, object] = {
        "profile_id": "prof_1",
        "paper_id": "pap_1",
        "title": "A Paper",
        "abstract": "This paper studies X.",
        "domain": ProfileField(value="NLP"),
        "research_problem": ProfileField(value="Solving Y"),
    }
    kwargs.update(overrides)
    return ResearchProfile(**kwargs)  # type: ignore[arg-type]


def test_minimal_profile_has_expected_defaults() -> None:
    profile = _minimal_profile()
    assert profile.grounding == "full_text"
    assert profile.workspace_id is None
    assert profile.keywords == []
    assert profile.extraction_confidence == Confidence.LOW
    assert isinstance(profile.tokens, TokenUsage)
    assert profile.subdomains.items == []


def test_title_and_abstract_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        _minimal_profile(title="")
    with pytest.raises(ValidationError):
        _minimal_profile(abstract="   ")


def test_year_outside_reasonable_range_is_dropped_not_rejected() -> None:
    profile = _minimal_profile(year=1200)
    assert profile.year is None
    profile2 = _minimal_profile(year=3000)
    assert profile2.year is None


def test_year_within_range_is_kept() -> None:
    profile = _minimal_profile(year=2023)
    assert profile.year == 2023


def test_keywords_are_deduplicated_lowercased_and_length_limited() -> None:
    profile = _minimal_profile(
        keywords=["Deep Learning", "deep learning", "NLP", "a b c d e f g h", ""]
    )
    assert profile.keywords == ["deep learning", "nlp"]


def test_keywords_capped_at_25() -> None:
    profile = _minimal_profile(keywords=[f"kw{i}" for i in range(40)])
    assert len(profile.keywords) == 25


def test_profile_field_default_status_is_unverified() -> None:
    field = ProfileField(value="x")
    assert field.status == ProvenanceStatus.UNVERIFIED
    assert field.source_span is None


def test_source_span_quote_max_length_enforced() -> None:
    with pytest.raises(ValidationError):
        SourceSpan(paper_id="pap_1", quote="x" * 401)
    span = SourceSpan(paper_id="pap_1", quote="x" * 400)
    assert len(span.quote) == 400


def test_profile_list_holds_items() -> None:
    profile_list = ProfileList(items=[ProfileField(value="a"), ProfileField(value="b")])
    assert len(profile_list.items) == 2


def test_created_at_and_updated_at_default_to_now() -> None:
    before = dt.datetime.now(dt.timezone.utc)
    profile = _minimal_profile()
    assert profile.created_at >= before
    assert profile.updated_at >= before
