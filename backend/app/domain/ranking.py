"""Ranking domain models (Data Model §4; Architecture §3 S9-S10).

The seven signals, the initial `w0-initial` weights, the retained
per-signal `SignalScores`, the signal-derived `RankingExplanation`, and the
persisted `RankedPaper`. All arithmetic is deterministic and lives in
app/services/ranking/* -- nothing here or there calls an LLM (the optional
prose rephrase in explain.py is the single, constrained exception and never
touches `bullet_reasons`).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.profile import Confidence

SIGNAL_NAMES: tuple[str, ...] = (
    "semantic_doc",
    "semantic_chunk",
    "problem_sim",
    "method_sim",
    "dataset_overlap",
    "citation",
    "recency",
)


class RankingWeights(BaseModel):
    """INITIAL EXPERIMENTAL VALUES chosen from the literature review (Data
    Model §4), NOT empirically optimal. Tuning is Phase 16's job -- the
    tuned set will be checked in as `w1-*` alongside the eval run that
    produced it. `version` is stamped on every RankedPaper for provenance.
    """

    version: str = "w0-initial"
    semantic_doc: float = 0.28
    semantic_chunk: float = 0.14
    problem_sim: float = 0.18
    method_sim: float = 0.14
    dataset_overlap: float = 0.08
    citation: float = 0.12
    recency: float = 0.06

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in SIGNAL_NAMES}


class SignalScores(BaseModel):
    semantic_doc: float | None = None
    semantic_chunk: float | None = None
    problem_sim: float | None = None
    method_sim: float | None = None
    dataset_overlap: float | None = None
    citation: float | None = None
    recency: float | None = None

    def available(self) -> dict[str, float]:
        """The signals that were actually computed (a `None` means the
        input for that signal was missing -> fuse.py renormalises over the
        rest)."""
        return {name: value for name in SIGNAL_NAMES if (value := getattr(self, name)) is not None}


class RankingExplanation(BaseModel):
    bullet_reasons: list[str]
    prose: str
    signals_used: list[str] = Field(default_factory=list)
    template_only: bool = False  # True unless an LLM rephrase of the bullets succeeded


class RankedPaper(BaseModel):
    candidate_id: str
    signals: SignalScores
    weights_version: str
    fused_score: float
    rerank_score: float | None = None
    final_rank: int
    band: Confidence
    explanation: RankingExplanation
