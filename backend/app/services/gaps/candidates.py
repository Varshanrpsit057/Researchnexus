"""Deterministic gap-candidate rules (Architecture §1.1 "Gap: rule-derived
candidates ... Deterministic"; Roadmap Phase 11).

Rules run over the cross-paper matrix and produce `GapCandidate`s -- the
LLM never sees the papers before a rule has fired, so it "cannot introduce
a gap not derivable from the matrix + evidence" (Data Model §8). Each
candidate carries the deterministic `facts` the constrained articulation
step is allowed to phrase, plus real `GapEvidence` spans.

Implemented rules: METHOD_GAP (`method_coverage`), DATASET_GAP
(`dataset_divergence`), EVALUATION_GAP (`metric_divergence`),
GENERALIZATION_GAP (`shared_limitation`), UNEXPLORED_COMBINATION
(`method_dataset_combination`), TEMPORAL_GAP (`temporal_staleness`), and
CONTRADICTION (`trail_contradiction`, from Phase 7
`POTENTIALLY_CONTRADICTORY` edges). DOMAIN_GAP and PERFORMANCE_GAP are
valid enum values whose deterministic rule is deferred (they need a domain
taxonomy / numeric-metric parsing) -- see the Phase 11 report.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.domain.gap import EvidenceRole, GapEvidence, GapType
from app.domain.trail import RelationshipType, TrailEdge
from app.services.gaps.matrix import GapMatrix

_MIN = 2
_DEFAULT_TEMPORAL_YEARS = 4
_CONTEXT_FACETS = ("problem", "subdomain", "dataset")


@dataclass
class GapCandidate:
    gap_type: GapType
    detection_rule: str
    supporting_papers: list[str]
    supporting_evidence: list[GapEvidence] = field(default_factory=list)
    conflicting_evidence: list[GapEvidence] = field(default_factory=list)
    affected_methods: list[str] = field(default_factory=list)
    affected_datasets: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    evidence_coverage: float = 0.0  # set by evidence.assemble


def _context_values(matrix: GapMatrix, paper_id: str) -> set[str]:
    vals: set[str] = set()
    for facet in _CONTEXT_FACETS:
        vals |= matrix.values(paper_id, facet)
    return vals


def _evidence(matrix: GapMatrix, paper_id: str, facet: str, value: str | None, role: str) -> GapEvidence | None:
    entries = matrix.entries(paper_id, facet)
    chosen = None
    if value is not None:
        chosen = next((e for e in entries if e.value == value and e.span is not None), None)
    if chosen is None:
        chosen = next((e for e in entries if e.span is not None), None)
    if chosen is None or chosen.span is None:
        return None
    return GapEvidence(paper_id=paper_id, span=chosen.span, role=role)


def _collect(items: Iterable[GapEvidence | None]) -> list[GapEvidence]:
    return [e for e in items if e is not None]


def _distinct(evidence: list[GapEvidence]) -> int:
    return len({e.paper_id for e in evidence})


# --- rules ---------------------------------------------------------------


def _method_coverage(matrix: GapMatrix) -> list[GapCandidate]:
    out: list[GapCandidate] = []
    for value, users in matrix.value_counts("method").items():
        missing = matrix.papers_without("method", value)
        user_context: set[str] = set()
        for u in users:
            user_context |= _context_values(matrix, u)
        relevant_missing = [p for p in missing if _context_values(matrix, p) & user_context]
        if len(relevant_missing) < _MIN:
            continue
        ev = _collect(
            _evidence(matrix, p, "problem", None, EvidenceRole.SHARED_CONTEXT.value) for p in relevant_missing
        )
        if _distinct(ev) < _MIN:
            continue
        raw = next((e.raw for u in users for e in matrix.entries(u, "method") if e.value == value), value)
        # the using paper's own words: what shows the method exists at all
        use = next(((u, e) for u in users for e in matrix.entries(u, "method") if e.value == value and e.span), None)
        facts = {
            "facet": "method", "value": raw, "used_by": users,
            "missing_from": [e.paper_id for e in ev], "shared_context": sorted(user_context)[:5],
        }
        missing_from = [e.paper_id for e in ev]
        if use is not None and use[1].span is not None:
            facts["method_quote"] = use[1].span.quote
            # shown with the gap (remediation Phase 16): without it a method gap's evidence was only
            # the other papers' problem statements, and nothing a reader saw named the method at all.
            # The gap's papers stay the ones that lack it (counts, confidence and ids are theirs).
            ev = [GapEvidence(paper_id=use[0], span=use[1].span, role=EvidenceRole.SUPPORTS_GAP.value), *ev]
        out.append(
            GapCandidate(
                gap_type=GapType.METHOD_GAP,
                detection_rule="method_coverage",
                supporting_papers=missing_from,
                supporting_evidence=ev,
                affected_methods=[raw],
                facts=facts,
            )
        )
    return out


def _divergence(matrix: GapMatrix, facet: str, gap_type: GapType, rule: str) -> list[GapCandidate]:
    counts = matrix.value_counts(facet)
    users = [pid for pid in matrix.paper_ids() if matrix.values(pid, facet)]
    if len(users) < _MIN or any(len(papers) >= _MIN for papers in counts.values()):
        return []
    ev = _collect(_evidence(matrix, p, facet, None, EvidenceRole.SUPPORTS_GAP.value) for p in users)
    if _distinct(ev) < _MIN:
        return []
    per_paper = {p: sorted(matrix.values(p, facet)) for p in users}
    raws = sorted({e.raw for p in users for e in matrix.entries(p, facet)})
    cand = GapCandidate(
        gap_type=gap_type,
        detection_rule=rule,
        supporting_papers=[e.paper_id for e in ev],
        supporting_evidence=ev,
        facts={"facet": facet, "no_shared_value": True, "per_paper": per_paper, "values": raws},
    )
    if facet == "dataset":
        cand.affected_datasets = raws
    return [cand]


def _shared_limitation(matrix: GapMatrix) -> list[GapCandidate]:
    out: list[GapCandidate] = []
    for value, papers in matrix.value_counts("limitation").items():
        if len(papers) < _MIN:
            continue
        ev = _collect(
            _evidence(matrix, p, "limitation", value, EvidenceRole.SUPPORTS_GAP.value) for p in papers
        )
        if _distinct(ev) < _MIN:
            continue
        raw = next((e.raw for p in papers for e in matrix.entries(p, "limitation") if e.value == value), value)
        out.append(
            GapCandidate(
                gap_type=GapType.GENERALIZATION_GAP,
                detection_rule="shared_limitation",
                supporting_papers=[e.paper_id for e in ev],
                supporting_evidence=ev,
                facts={
                    "facet": "limitation", "value": raw,
                    "papers": [e.paper_id for e in ev], "limitation_agreement": True,
                },
            )
        )
    return out


def _unexplored_combination(matrix: GapMatrix) -> list[GapCandidate]:
    out: list[GapCandidate] = []
    methods = {v: ps for v, ps in matrix.value_counts("method").items() if len(ps) >= _MIN}
    datasets = {v: ps for v, ps in matrix.value_counts("dataset").items() if len(ps) >= _MIN}
    for mv, m_papers in methods.items():
        for dv, d_papers in datasets.items():
            if set(m_papers) & set(d_papers):
                continue
            combined = {
                pid
                for pid in matrix.paper_ids()
                if mv in matrix.values(pid, "method") and dv in matrix.values(pid, "dataset")
            }
            if combined:
                continue
            ev = _collect(
                [
                    _evidence(matrix, m_papers[0], "method", mv, EvidenceRole.SHARED_CONTEXT.value),
                    _evidence(matrix, d_papers[0], "dataset", dv, EvidenceRole.SHARED_CONTEXT.value),
                ]
            )
            if _distinct(ev) < _MIN:
                continue
            m_raw = next((e.raw for e in matrix.entries(m_papers[0], "method") if e.value == mv), mv)
            d_raw = next((e.raw for e in matrix.entries(d_papers[0], "dataset") if e.value == dv), dv)
            out.append(
                GapCandidate(
                    gap_type=GapType.UNEXPLORED_COMBINATION,
                    detection_rule="method_dataset_combination",
                    supporting_papers=[e.paper_id for e in ev],
                    supporting_evidence=ev,
                    affected_methods=[m_raw],
                    affected_datasets=[d_raw],
                    facts={"method": m_raw, "dataset": d_raw, "method_papers": m_papers, "dataset_papers": d_papers},
                )
            )
    return out


def _temporal_staleness(matrix: GapMatrix, years: int = _DEFAULT_TEMPORAL_YEARS) -> list[GapCandidate]:
    newest = matrix.newest_year()
    year_by_paper = matrix.papers_with_year()
    if newest is None or not year_by_paper:
        return []
    out: list[GapCandidate] = []
    for facet in ("problem", "subdomain"):
        for value, papers in matrix.value_counts(facet).items():
            dated = [p for p in papers if p in year_by_paper]
            if len(dated) < _MIN:
                continue
            newest_with = max(year_by_paper[p] for p in dated)
            if newest - newest_with < years:
                continue
            ev = _collect(
                _evidence(matrix, p, facet, value, EvidenceRole.SHARED_CONTEXT.value) for p in dated
            )
            if _distinct(ev) < _MIN:
                continue
            raw = next((e.raw for p in dated for e in matrix.entries(p, facet) if e.value == value), value)
            out.append(
                GapCandidate(
                    gap_type=GapType.TEMPORAL_GAP,
                    detection_rule="temporal_staleness",
                    supporting_papers=[e.paper_id for e in ev],
                    supporting_evidence=ev,
                    facts={
                        "topic": raw, "newest_with_topic": newest_with,
                        "workspace_newest": newest, "gap_years": newest - newest_with,
                    },
                )
            )
    return out


def contradiction_candidates(trail_edges: list[TrailEdge]) -> list[GapCandidate]:
    out: list[GapCandidate] = []
    for edge in trail_edges:
        if edge.relationship_type is not RelationshipType.POTENTIALLY_CONTRADICTORY:
            continue
        conflicting = [
            GapEvidence(paper_id=e.span.paper_id, span=e.span, role=EvidenceRole.CONFLICTS_WITH_GAP.value)
            for e in edge.evidence
        ]
        papers = sorted({edge.source_paper_id, edge.target_paper_id})
        if len(papers) < _MIN or _distinct(conflicting) < _MIN:
            continue
        out.append(
            GapCandidate(
                gap_type=GapType.CONTRADICTION,
                detection_rule="trail_contradiction",
                supporting_papers=papers,
                supporting_evidence=[
                    GapEvidence(paper_id=e.paper_id, span=e.span, role=EvidenceRole.SHARED_CONTEXT.value)
                    for e in conflicting
                ],
                conflicting_evidence=conflicting,
                facts={"edge_id": edge.edge_id, "claims": [e.span.quote for e in edge.evidence]},
            )
        )
    return out


def rule_facts(candidate: GapCandidate, titles: dict[str, str]) -> list[str]:
    """What the rule itself established by comparing the papers' profiles,
    stated plainly. A gap is often an absence ("no paper that shares this
    problem uses X"): no quote can state what a paper doesn't do, so the
    self-support check reads these facts next to the quotes. They say only
    what the rule computed -- never that a limitation is unresolved or that a
    method would help."""
    f = candidate.facts

    def names(ids: Iterable[str]) -> str:
        return "; ".join(f'"{titles.get(pid, pid)}"' for pid in ids)

    rule = candidate.detection_rule
    if rule == "method_coverage":
        lines = [
            f"The research profiles list {f['value']} as a method of {names(f.get('used_by', []))}. "
            f"It is not listed as a method of any of these papers, which share its research setting: "
            f"{names(f.get('missing_from', []))}."
        ]
        if f.get("method_quote"):
            lines.append(f"The paper using it says: {f['method_quote']}")
        return lines
    if rule in ("dataset_divergence", "metric_divergence"):
        per = "; ".join(f'"{titles.get(pid, pid)}": {", ".join(vals)}' for pid, vals in f.get("per_paper", {}).items())
        return [f"The research profiles list these {f['facet']}s, and no {f['facet']} is listed by two papers: {per}."]
    if rule == "shared_limitation":
        return [f"The research profiles of {names(f.get('papers', []))} each list the limitation: {f['value']}."]
    if rule == "method_dataset_combination":
        return [
            f"The research profiles list the method {f['method']} for {names(f.get('method_papers', []))} and the dataset "
            f"{f['dataset']} for {names(f.get('dataset_papers', []))}; no paper's profile lists both."
        ]
    if rule == "temporal_staleness":
        return [
            f"The newest workspace paper on {f['topic']} is from {f['newest_with_topic']}; the newest workspace paper "
            f"overall is from {f['workspace_newest']}, {f['gap_years']} years later."
        ]
    return []


def generate_candidates(matrix: GapMatrix, *, gap_types: set[GapType] | None) -> list[GapCandidate]:
    rules = [
        _method_coverage(matrix),
        _divergence(matrix, "dataset", GapType.DATASET_GAP, "dataset_divergence"),
        _divergence(matrix, "metric", GapType.EVALUATION_GAP, "metric_divergence"),
        _shared_limitation(matrix),
        _unexplored_combination(matrix),
        _temporal_staleness(matrix),
    ]
    cands = [c for group in rules for c in group]
    if gap_types is not None:
        cands = [c for c in cands if c.gap_type in gap_types]
    return cands
