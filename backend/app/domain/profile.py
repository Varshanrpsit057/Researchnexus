"""ResearchProfile domain model (Roadmap Phase 3; Data Model §2).

Every "understanding" field is a `ProfileField`/`ProfileList` carrying its
value plus provenance (a `SourceSpan` into the paper's own persisted text)
and a `ProvenanceStatus` -- never a bare LLM-asserted string (Architecture
§9 IEEE-limitation traceability: this is the evidence trail a future
research-gap workflow needs). Bibliographic fields (title/abstract/authors/
year/venue/doi/arxiv_id) are deterministic, copied from the already-
validated Paper row -- this is the paper's first LLM use (Architecture §3
S4), but the LLM never touches bibliographic metadata.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

_CURRENT_YEAR_CEILING = datetime.now(timezone.utc).year + 1
_MIN_YEAR = 1950
_MAX_KEYWORD_WORDS = 5
_MAX_KEYWORDS = 25
_MAX_QUOTE_LEN = 400


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProvenanceStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    USER_EDITED = "user_edited"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TokenUsage(BaseModel):
    prompt: int = 0
    completion: int = 0


class SourceSpan(BaseModel):
    paper_id: str
    section: str | None = None
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str = Field(max_length=_MAX_QUOTE_LEN)


class ReportedValue(BaseModel):
    """The value a paper reports for a field -- an evaluation metric's
    "95.83%" -- verbatim. `verified` only when it is written in the field's
    own verified evidence; an unverified value is kept to say one was
    claimed, never shown as the paper's result (remediation Phase 6)."""

    text: str
    status: ProvenanceStatus = ProvenanceStatus.UNVERIFIED


class ProfileField(BaseModel):
    value: str
    source_span: SourceSpan | None = None
    status: ProvenanceStatus = ProvenanceStatus.UNVERIFIED
    reported_value: ReportedValue | None = None


class ProfileList(BaseModel):
    items: list[ProfileField] = Field(default_factory=list)


class ResearchProfile(BaseModel):
    profile_id: str
    paper_id: str
    workspace_id: str | None = None
    grounding: str = "full_text"  # "full_text" (seed) | "abstract" (discovered) -- Data Model §2

    # --- bibliographic (deterministic, not LLM) ---
    title: str
    abstract: str
    # False when no abstract was found and `abstract` is stand-in text (the
    # start of the body): it must not be shown as the paper's abstract
    abstract_found: bool = True
    # at most two of the abstract's own sentences (services/profile/refine.py)
    summary: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None

    # --- understanding (LLM-extracted, validated, provenance-checked) ---
    domain: ProfileField
    subdomains: ProfileList = Field(default_factory=ProfileList)
    research_problem: ProfileField
    research_questions: ProfileList = Field(default_factory=ProfileList)
    objectives: ProfileList = Field(default_factory=ProfileList)
    keywords: list[str] = Field(default_factory=list)
    methods: ProfileList = Field(default_factory=ProfileList)
    models: ProfileList = Field(default_factory=ProfileList)
    algorithms: ProfileList = Field(default_factory=ProfileList)
    datasets: ProfileList = Field(default_factory=ProfileList)
    evaluation_metrics: ProfileList = Field(default_factory=ProfileList)
    findings: ProfileList = Field(default_factory=ProfileList)
    limitations: ProfileList = Field(default_factory=ProfileList)
    future_work: ProfileList = Field(default_factory=ProfileList)
    important_entities: ProfileList = Field(default_factory=ProfileList)
    cited_methods: ProfileList = Field(default_factory=ProfileList)

    # --- derived for discovery (Roadmap P4/P5 seed S5 with these) ---
    candidate_search_queries: list[str] = Field(default_factory=list)

    extraction_confidence: Confidence = Confidence.LOW
    extraction_model: str | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("title", "abstract")
    @classmethod
    def _non_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v

    @field_validator("year")
    @classmethod
    def _year_in_range_or_none(cls, v: int | None) -> int | None:
        if v is not None and not (_MIN_YEAR <= v <= _CURRENT_YEAR_CEILING):
            return None
        return v

    @field_validator("keywords")
    @classmethod
    def _clean_keywords(cls, v: list[str]) -> list[str]:
        seen: list[str] = []
        for kw in v:
            normalized = " ".join(kw.strip().lower().split())
            if not normalized or len(normalized.split()) > _MAX_KEYWORD_WORDS:
                continue
            if normalized not in seen:
                seen.append(normalized)
        return seen[:_MAX_KEYWORDS]
