"""Deterministic rule-based relationship typing (Architecture §3 S11
`rules.py`). Each rule is a pure function that either fires (returning a
`RuleResult` with at least one verbatim `Evidence` span) or returns `None`.
Thresholds are fixed `w0` values -- calibration is Phase 16 (ablation A9);
they are set conservatively for a high-precision MVP ("prefer UNKNOWN over
unsupported relationships": no rule firing == no edge).

`POTENTIALLY_CONTRADICTORY` is only ever *proposed* here
(`is_contradiction_candidate=True`); it becomes an edge only after the NLI
verification pass in contradiction.py finds a quotable span in BOTH papers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.candidate import CitationRelationship
from app.domain.profile import Confidence, SourceSpan
from app.domain.ranking import SignalScores
from app.domain.trail import Evidence, RelationshipType


@dataclass(frozen=True)
class TrailThresholds:
    semantic_similar: float = 0.65
    problem_similar: float = 0.60
    problem_related_min: float = 0.45  # weak topical overlap, used by RECENT / contradiction seeding
    method_extension_min: float = 0.55
    method_competing_max: float = 0.40
    problem_competing_min: float = 0.55
    dataset_overlap_min: float = 0.50
    foundational_year_gap: int = 1
    recent_year_gap: int = 1
    high_confidence_year_gap: int = 2


@dataclass
class TrailContext:
    seed_paper_id: str
    seed_year: int | None
    seed_title: str
    seed_abstract: str | None
    seed_datasets: list[tuple[str, SourceSpan | None]]
    seed_methods: list[str]
    seed_findings: list[tuple[str, SourceSpan | None]]
    # for evidence selection (evidence.py): the seed's parsed reference list,
    # and its research problem / methods with their verified source spans
    seed_references: list[dict] = field(default_factory=list)
    seed_problem: tuple[str, SourceSpan | None] | None = None
    seed_method_spans: list[tuple[str, SourceSpan | None]] = field(default_factory=list)


@dataclass
class CandidateView:
    candidate_id: str
    paper_id: str
    title: str
    abstract: str | None
    year: int | None
    citation_relationship: CitationRelationship
    citation_hops: int | None
    signals: SignalScores


@dataclass
class RuleResult:
    relationship_type: RelationshipType
    rule_fired: str
    evidence: list[Evidence]
    rule_confidence: Confidence
    signal_agreement: int
    is_contradiction_candidate: bool = False
    supporting_signals: dict[str, float] = field(default_factory=dict)


_SPECIFIC_TYPES = {
    RelationshipType.FOUNDATIONAL,
    RelationshipType.RECENT,
    RelationshipType.METHOD_EXTENSION,
    RelationshipType.COMPETING,
}
_CONTRADICTION_CUES = (
    "does not",
    "do not",
    "no significant",
    "fails to",
    "contrary to",
    "contradict",
    "unlike prior",
    "in contrast to",
    "we find no",
    "cannot",
)


def _get(signals: SignalScores, name: str) -> float | None:
    return getattr(signals, name)


def _signal_agreement(signals: SignalScores, threshold: float = 0.5) -> int:
    return sum(1 for v in signals.available().values() if v >= threshold)


def _target_span(cand: CandidateView, quote: str, role: str) -> Evidence:
    return Evidence(span=SourceSpan(paper_id=cand.paper_id, quote=quote[:400]), role=role)


def _rule_foundational(ctx: TrailContext, cand: CandidateView, t: TrailThresholds) -> RuleResult | None:
    if cand.citation_relationship is not CitationRelationship.CITED_BY_SEED:
        return None
    if ctx.seed_year is None or cand.year is None or cand.year > ctx.seed_year - t.foundational_year_gap:
        return None
    gap = ctx.seed_year - cand.year
    return RuleResult(
        relationship_type=RelationshipType.FOUNDATIONAL,
        rule_fired="cited_by_seed AND target_year < seed_year",
        evidence=[_target_span(cand, cand.title, "citation")],
        rule_confidence=Confidence.HIGH if gap >= t.high_confidence_year_gap else Confidence.MEDIUM,
        signal_agreement=_signal_agreement(cand.signals),
    )


def _rule_recent(ctx: TrailContext, cand: CandidateView, t: TrailThresholds) -> RuleResult | None:
    if ctx.seed_year is None or cand.year is None or cand.year < ctx.seed_year + t.recent_year_gap:
        return None
    problem = _get(cand.signals, "problem_sim")
    semantic = _get(cand.signals, "semantic_doc")
    best = max((s for s in (problem, semantic) if s is not None), default=None)
    if best is None or best < t.problem_related_min:
        return None
    return RuleResult(
        relationship_type=RelationshipType.RECENT,
        rule_fired="target_year > seed_year AND (problem_sim>=0.45 OR semantic_doc>=0.45)",
        evidence=[_target_span(cand, f"{cand.title} ({cand.year})", "recency")],
        rule_confidence=Confidence.HIGH if (cand.year - ctx.seed_year) >= t.high_confidence_year_gap and best >= t.problem_similar else Confidence.MEDIUM,
        signal_agreement=_signal_agreement(cand.signals),
    )


def _rule_dataset_related(ctx: TrailContext, cand: CandidateView, t: TrailThresholds) -> RuleResult | None:
    abstract = cand.abstract or ""
    named: list[Evidence] = []
    for name, seed_span in ctx.seed_datasets:
        if name and name.lower() in abstract.lower():
            idx = abstract.lower().find(name.lower())
            named.append(
                Evidence(
                    span=SourceSpan(
                        paper_id=cand.paper_id, char_start=idx, char_end=idx + len(name), quote=abstract[idx : idx + len(name)]
                    ),
                    role="shared_dataset",
                )
            )
            if seed_span is not None:
                named.append(Evidence(span=seed_span, role="seed_claim"))
    overlap = _get(cand.signals, "dataset_overlap")
    if not named and (overlap is None or overlap < t.dataset_overlap_min):
        return None
    evidence = named or [_target_span(cand, cand.title, "similarity_signal")]
    return RuleResult(
        relationship_type=RelationshipType.DATASET_RELATED,
        rule_fired="shared_dataset_name_in_target_abstract OR dataset_overlap>=0.5",
        evidence=evidence,
        rule_confidence=Confidence.HIGH if len(named) >= 2 else Confidence.MEDIUM,
        signal_agreement=_signal_agreement(cand.signals),
    )


def _rule_method_extension(ctx: TrailContext, cand: CandidateView, t: TrailThresholds) -> RuleResult | None:
    if cand.citation_relationship is not CitationRelationship.CITES_SEED:
        return None
    method = _get(cand.signals, "method_sim")
    if method is None or method < t.method_extension_min:
        return None
    return RuleResult(
        relationship_type=RelationshipType.METHOD_EXTENSION,
        rule_fired="cites_seed AND method_sim>=0.55",
        evidence=[_target_span(cand, cand.title, "citation")],
        rule_confidence=Confidence.HIGH if method >= t.problem_similar else Confidence.MEDIUM,
        signal_agreement=_signal_agreement(cand.signals),
    )


def _rule_competing(ctx: TrailContext, cand: CandidateView, t: TrailThresholds) -> RuleResult | None:
    if cand.citation_relationship is not CitationRelationship.NONE:
        return None
    problem = _get(cand.signals, "problem_sim")
    method = _get(cand.signals, "method_sim")
    if problem is None or method is None:
        return None
    if problem < t.problem_competing_min or method >= t.method_competing_max:
        return None
    return RuleResult(
        relationship_type=RelationshipType.COMPETING,
        rule_fired="problem_sim>=0.55 AND method_sim<0.40 AND citation_relationship=none",
        evidence=[_target_span(cand, cand.title, "competing_signal")],
        rule_confidence=Confidence.MEDIUM,
        signal_agreement=_signal_agreement(cand.signals),
    )


def _rule_similar(ctx: TrailContext, cand: CandidateView, t: TrailThresholds) -> RuleResult | None:
    semantic = _get(cand.signals, "semantic_doc")
    problem = _get(cand.signals, "problem_sim")
    hit = (semantic is not None and semantic >= t.semantic_similar) or (problem is not None and problem >= t.problem_similar)
    if not hit:
        return None
    return RuleResult(
        relationship_type=RelationshipType.SIMILAR,
        rule_fired="semantic_doc>=0.65 OR problem_sim>=0.60",
        evidence=[_target_span(cand, cand.title, "similarity_signal")],
        rule_confidence=Confidence.MEDIUM,
        signal_agreement=_signal_agreement(cand.signals),
    )


def _rule_contradiction_candidate(ctx: TrailContext, cand: CandidateView, t: TrailThresholds) -> RuleResult | None:
    if not ctx.seed_findings:
        return None
    problem = _get(cand.signals, "problem_sim")
    if problem is None or problem < t.problem_related_min:
        return None
    abstract_low = (cand.abstract or "").lower()
    if not any(cue in abstract_low for cue in _CONTRADICTION_CUES):
        return None
    return RuleResult(
        relationship_type=RelationshipType.POTENTIALLY_CONTRADICTORY,
        rule_fired="topical_overlap AND negation_cue_in_target_abstract AND seed_has_findings",
        evidence=[_target_span(cand, cand.abstract or cand.title, "target_claim")],
        rule_confidence=Confidence.LOW,
        signal_agreement=_signal_agreement(cand.signals),
        is_contradiction_candidate=True,
    )


_RULES = (
    _rule_foundational,
    _rule_recent,
    _rule_dataset_related,
    _rule_method_extension,
    _rule_competing,
    _rule_similar,
    _rule_contradiction_candidate,
)


def apply_rules(ctx: TrailContext, cand: CandidateView, *, thresholds: TrailThresholds) -> list[RuleResult]:
    fired = [result for rule in _RULES if (result := rule(ctx, cand, thresholds)) is not None]
    types = {r.relationship_type for r in fired}
    if RelationshipType.SIMILAR in types and types & _SPECIFIC_TYPES:
        fired = [r for r in fired if r.relationship_type is not RelationshipType.SIMILAR]
    return fired
