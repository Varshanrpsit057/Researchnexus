"""Ranking domain models (Data Model §4; Architecture §3 S9-S10).

The seven signals, the initial `w0-initial` weights, the retained
per-signal `SignalScores`, the signal-derived `RankingExplanation`, and the
persisted `RankedPaper`. All arithmetic is deterministic and lives in
app/services/ranking/* -- nothing here or there calls an LLM (the optional
prose rephrase in explain.py is the single, constrained exception and never
touches `bullet_reasons`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.profile import Confidence

SIGNAL_NAMES: tuple[str, ...] = (
    "semantic_doc",
    "semantic_chunk",
    "problem_sim",
    "method_sim",
    "dataset_overlap",
    "citation",
    "recency",
    "publisher",
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
    # published by a publisher the reader prefers (remediation, 2026-10-02);
    # the initial weights predate it and give it none
    publisher: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in SIGNAL_NAMES}


# The criteria a researcher weighs (remediation Phase 9; "publisher" added
# 2026-10-02), and the computed signals each one stands for. "topic" counts
# document- and passage-level similarity together, 2:1, as the initial
# weights do.
CRITERIA: tuple[str, ...] = ("topic", "problem", "methods", "datasets", "citations", "recency", "publisher")
CRITERION_SIGNALS: dict[str, dict[str, float]] = {
    "topic": {"semantic_doc": 2 / 3, "semantic_chunk": 1 / 3},
    "problem": {"problem_sim": 1.0},
    "methods": {"method_sim": 1.0},
    "datasets": {"dataset_overlap": 1.0},
    "citations": {"citation": 1.0},
    "recency": {"recency": 1.0},
    "publisher": {"publisher": 1.0},
}
_CRITERIA_VERSION_PREFIX = "c-"


class RankingCriteria(BaseModel):
    """How much each criterion counts in a ranking, 0-100. Only the
    proportions matter: (2, 1, 0, ...) ranks exactly like (40, 20, 0, ...).
    The defaults are the initial weights plus a preference for papers from
    IEEE, Springer, ACM and Elsevier (the reader's choice, 2026-10-02). At
    least one must count."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    topic: int = Field(default=42, ge=0, le=100)
    problem: int = Field(default=18, ge=0, le=100)
    methods: int = Field(default=14, ge=0, le=100)
    datasets: int = Field(default=8, ge=0, le=100)
    citations: int = Field(default=12, ge=0, le=100)
    recency: int = Field(default=6, ge=0, le=100)
    publisher: int = Field(default=15, ge=0, le=100)

    @model_validator(mode="after")
    def _something_counts(self) -> RankingCriteria:
        if sum(self.values()) == 0:
            raise ValueError("at least one ranking criterion must count for something")
        return self

    def values(self) -> tuple[int, ...]:
        return tuple(getattr(self, name) for name in CRITERIA)

    def to_weights(self) -> RankingWeights:
        """The fusion weights, stamped with a version that records these
        criteria (`c-<topic>.<problem>.<methods>.<datasets>.<citations>.<recency>.<publisher>`);
        the initial weights (no publisher preference) keep their own version."""
        if self == _INITIAL:
            return RankingWeights()
        total = sum(self.values())
        weights = {
            signal: getattr(self, criterion) / total * share
            for criterion, signals in CRITERION_SIGNALS.items()
            for signal, share in signals.items()
        }
        return RankingWeights(version=_CRITERIA_VERSION_PREFIX + ".".join(str(v) for v in self.values()), **weights)

    @classmethod
    def from_weights_version(cls, version: str) -> RankingCriteria | None:
        """The criteria a saved ranking was made with, read from its weights
        version; None for a version that doesn't record them."""
        if version == RankingWeights().version:
            return _INITIAL
        if not version.startswith(_CRITERIA_VERSION_PREFIX):
            return None
        parts = version[len(_CRITERIA_VERSION_PREFIX):].split(".")
        if len(parts) == len(CRITERIA) - 1:
            parts.append("0")  # saved before the publisher criterion existed
        if len(parts) != len(CRITERIA) or not all(p.isdigit() for p in parts):
            return None
        try:
            return cls(**dict(zip(CRITERIA, (int(p) for p in parts), strict=True)))
        except ValueError:
            return None


# the initial weights, as criteria: no publisher preference
_INITIAL = RankingCriteria(publisher=0)


class SignalScores(BaseModel):
    semantic_doc: float | None = None
    semantic_chunk: float | None = None
    problem_sim: float | None = None
    method_sim: float | None = None
    dataset_overlap: float | None = None
    citation: float | None = None
    recency: float | None = None
    publisher: float | None = None  # 1.0 from a preferred publisher, else 0.0

    def available(self) -> dict[str, float]:
        """The signals that were actually computed (a `None` means the
        input for that signal was missing -> fuse.py renormalises over the
        rest)."""
        return {name: value for name in SIGNAL_NAMES if (value := getattr(self, name)) is not None}


class SignalContribution(BaseModel):
    """One signal's part in a paper's score: its value, the weight it carried
    (renormalised over the signals that could be computed for this paper),
    and what it added -- weight x value. The contributions sum to the fused score."""

    signal: str
    value: float
    weight: float
    contribution: float


class RankingExplanation(BaseModel):
    bullet_reasons: list[str]
    prose: str
    signals_used: list[str] = Field(default_factory=list)
    template_only: bool = False  # True unless an LLM rephrase of the bullets succeeded
    # remediation Phase 9: the actual decision -- each computed signal's
    # contribution (largest first), and the signals that couldn't be computed
    contributions: list[SignalContribution] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)


class RankedPaper(BaseModel):
    candidate_id: str
    signals: SignalScores
    weights_version: str
    fused_score: float
    rerank_score: float | None = None
    final_rank: int
    band: Confidence
    explanation: RankingExplanation
