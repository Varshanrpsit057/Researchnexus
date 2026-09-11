"""ResearchDirection domain model (Data Model §9 / §13; Roadmap Phase 12).

A direction is always tied to an **accepted** `ResearchGap` and traceable
to that gap's evidence (`supporting_evidence` is the gap's spans). The LLM
phrases the wording; it may propose a new `suggested_method`, but a
technical term in `proposal` / `motivation` that is neither in the gap's
grounding vocabulary nor this direction's own `suggested_method` /
`possible_dataset` causes the direction to be dropped
(`services/directions/generate.py`).

`kind` is mandatory (Data Model §9): `evidence_backed_inference` when the
direction stays within the gap's evidence, `llm_hypothesis` when it
proposes something new. `critique.feasibility` is always treated as
uncertain (capped, never "high") per Si et al. `confidence` is a band enum
-- calibration is Phase 16.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.domain.gap import GapEvidence
from app.domain.profile import Confidence

_CRITIQUE_KEYS = ("novelty", "specificity", "feasibility", "groundedness")
_FEASIBILITY_CAP = 3  # feasibility is explicitly uncertain -- never claimed "high"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DirectionKind(str, Enum):
    EVIDENCE_BACKED_INFERENCE = "evidence_backed_inference"
    LLM_HYPOTHESIS = "llm_hypothesis"


class DirectionUserState(str, Enum):
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class ResearchDirection(BaseModel):
    direction_id: str
    workspace_id: str
    gap_id: str
    proposal: str
    motivation: str
    supporting_evidence: list[GapEvidence]
    related_papers: list[str] = Field(default_factory=list)
    suggested_method: str = ""
    possible_dataset: str | None = None
    evaluation_strategy: str = ""
    risks: list[str] = Field(default_factory=list)
    kind: str
    critique: dict = Field(default_factory=dict)
    confidence: Confidence = Confidence.LOW
    confidence_basis: dict = Field(default_factory=dict)
    flags: list[str] = Field(default_factory=list)
    user_state: str = DirectionUserState.CANDIDATE.value
    generated_at: datetime = Field(default_factory=_utcnow)
    generator_model: str | None = None

    @field_validator("supporting_evidence")
    @classmethod
    def _has_evidence(cls, v: list[GapEvidence]) -> list[GapEvidence]:
        if not v:
            raise ValueError("a ResearchDirection must inherit the accepted gap's evidence spans")
        return v

    @field_validator("kind")
    @classmethod
    def _kind_is_labelled(cls, v: str) -> str:
        if v not in {k.value for k in DirectionKind}:
            raise ValueError("kind must be evidence_backed_inference or llm_hypothesis")
        return v

    @field_validator("critique")
    @classmethod
    def _critique_scores_in_range(cls, v: dict) -> dict:
        for key in _CRITIQUE_KEYS:
            if key in v:
                v[key] = max(1, min(5, int(v[key])))
        if "feasibility" in v:
            v["feasibility"] = min(_FEASIBILITY_CAP, v["feasibility"])
        return v
