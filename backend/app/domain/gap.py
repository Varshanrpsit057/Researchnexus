"""ResearchGap domain models (Data Model §8 / §13; Roadmap Phase 11 --
the third contribution area).

Directly addresses the tracked IEEE BigData 2024 limitation (Architecture
§9): the source paper generates meta-analysis prose with no explicit,
auditable, evidence-backed research-gap step. A `ResearchGap` here is only
ever created after a deterministic rule fires, >= 2 real papers supply
evidence spans, a constrained LLM phrases the statement from that evidence
(never inventing a claim), and a Self-RAG-style self-support check passes.

Hard invariants (enforced below):
- `supporting_papers` has >= 2 entries -- fewer and the candidate is dropped
  before a `ResearchGap` is constructed;
- `supporting_evidence` is non-empty and every entry carries a real
  `SourceSpan`;
- `confidence` is a band enum -- **never a percentage** (calibration is
  Phase 16).
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.domain.profile import Confidence, SourceSpan

MIN_SUPPORTING_PAPERS = 2


class GapType(str, Enum):
    METHOD_GAP = "METHOD_GAP"
    DATASET_GAP = "DATASET_GAP"
    EVALUATION_GAP = "EVALUATION_GAP"
    DOMAIN_GAP = "DOMAIN_GAP"
    PERFORMANCE_GAP = "PERFORMANCE_GAP"
    GENERALIZATION_GAP = "GENERALIZATION_GAP"
    CONTRADICTION = "CONTRADICTION"
    UNEXPLORED_COMBINATION = "UNEXPLORED_COMBINATION"
    TEMPORAL_GAP = "TEMPORAL_GAP"


class GapUserState(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class EvidenceRole(str, Enum):
    SUPPORTS_GAP = "supports_gap"
    CONFLICTS_WITH_GAP = "conflicts_with_gap"
    SHARED_CONTEXT = "shared_context"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GapEvidence(BaseModel):
    paper_id: str
    span: SourceSpan
    role: str = EvidenceRole.SUPPORTS_GAP.value


class ResearchGap(BaseModel):
    gap_id: str
    workspace_id: str
    statement: str
    gap_type: GapType
    supporting_papers: list[str]
    supporting_evidence: list[GapEvidence]
    conflicting_evidence: list[GapEvidence] = Field(default_factory=list)
    why_unaddressed: str = ""
    affected_methods: list[str] = Field(default_factory=list)
    affected_datasets: list[str] = Field(default_factory=list)
    evidence_coverage: float = 0.0
    novelty_assessment: str = "under-addressed in this workspace"
    confidence: Confidence = Confidence.LOW
    confidence_basis: dict = Field(default_factory=dict)
    proposed_direction: str = ""
    detection_rule: str = ""
    self_support_passed: bool = False
    user_state: str = GapUserState.CANDIDATE.value
    generated_at: datetime = Field(default_factory=_utcnow)
    generator_model: str | None = None

    @field_validator("supporting_papers")
    @classmethod
    def _at_least_two_papers(cls, v: list[str]) -> list[str]:
        if len(set(v)) < MIN_SUPPORTING_PAPERS:
            raise ValueError("a ResearchGap must have >= 2 distinct supporting papers")
        return v

    @field_validator("supporting_evidence")
    @classmethod
    def _has_evidence(cls, v: list[GapEvidence]) -> list[GapEvidence]:
        if not v:
            raise ValueError("a ResearchGap must carry at least one supporting evidence span")
        return v
