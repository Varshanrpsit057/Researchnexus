"""Typed research trail domain models (Data Model §5; Architecture §3 S11).

An edge is created only when a deterministic rule fires *and* at least one
verbatim `Evidence.span` is attached (Roadmap Phase 7: "Never create a
relationship without supporting evidence"). The LLM may raise
`detection_method` to `rule_llm_confirmed` and add a target span, but it can
never introduce a new relationship type or an unverified span
(app/services/trail/confirm_llm.py). `POTENTIALLY_CONTRADICTORY` is only
ever produced by the NLI verification pass with a span from BOTH papers.

Scoped to a `run_id` for the pre-workspace MVP (Roadmap Phase 7:
"pre-workspace variant on run_id"); `workspace_id` is wired in Phase 8.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.domain.profile import Confidence, SourceSpan


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RelationshipType(str, Enum):
    SIMILAR = "SIMILAR"
    FOUNDATIONAL = "FOUNDATIONAL"
    RECENT = "RECENT"
    COMPETING = "COMPETING"
    METHOD_EXTENSION = "METHOD_EXTENSION"
    DATASET_RELATED = "DATASET_RELATED"
    POTENTIALLY_CONTRADICTORY = "POTENTIALLY_CONTRADICTORY"


class DetectionMethod(str, Enum):
    RULE = "rule"
    RULE_LLM_CONFIRMED = "rule_llm_confirmed"
    CONTRADICTION_NLI = "contradiction_nli"
    USER = "user"


class UserState(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Evidence(BaseModel):
    span: SourceSpan
    role: str  # "seed_claim" | "target_claim" | "shared_dataset" | "citation" | "similarity_signal" | ...


class TrailEdge(BaseModel):
    edge_id: str
    run_id: str
    workspace_id: str | None = None
    source_paper_id: str  # the seed at trail-build time
    target_paper_id: str
    relationship_type: RelationshipType
    detection_method: DetectionMethod
    rule_fired: str | None = None
    llm_confirmed: bool = False
    evidence: list[Evidence]
    supporting_references: list[str] = Field(default_factory=list)
    confidence: Confidence
    confidence_basis: dict = Field(default_factory=dict)
    user_state: str = "pending"
    created_at: datetime = Field(default_factory=_utcnow)

    @field_validator("evidence")
    @classmethod
    def _at_least_one_evidence(cls, v: list[Evidence]) -> list[Evidence]:
        if not v:
            raise ValueError("a TrailEdge must carry at least one piece of evidence")
        return v
