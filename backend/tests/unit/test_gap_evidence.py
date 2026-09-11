from __future__ import annotations

from app.domain.gap import EvidenceRole, GapEvidence, GapType
from app.domain.profile import SourceSpan
from app.services.gaps.candidates import GapCandidate
from app.services.gaps.evidence import assemble


def _ev(pid: str, *, grounded: bool = True, role: str = EvidenceRole.SUPPORTS_GAP.value) -> GapEvidence:
    span = SourceSpan(
        paper_id=pid,
        section="Body" if grounded else None,
        char_start=5 if grounded else None,
        char_end=15 if grounded else None,
        quote=f"quote from {pid}",
    )
    return GapEvidence(paper_id=pid, span=span, role=role)


def _cand(evidence: list[GapEvidence], *, gap_type: GapType = GapType.METHOD_GAP, conflicting: list | None = None) -> GapCandidate:
    return GapCandidate(
        gap_type=gap_type,
        detection_rule="r",
        supporting_papers=[e.paper_id for e in evidence],
        supporting_evidence=evidence,
        conflicting_evidence=conflicting or [],
    )


def test_candidate_with_fewer_than_two_supporting_papers_is_dropped() -> None:
    assert assemble(_cand([_ev("p1")]), min_papers=2) is None
    assert assemble(_cand([_ev("p1"), _ev("p1")]), min_papers=2) is None  # same paper twice


def test_candidate_with_two_distinct_papers_survives_and_dedupes_supporting_papers() -> None:
    out = assemble(_cand([_ev("p1"), _ev("p2"), _ev("p1")]), min_papers=2)
    assert out is not None
    assert out.supporting_papers == ["p1", "p2"]


def test_evidence_coverage_is_the_fraction_of_full_text_grounded_papers() -> None:
    out = assemble(_cand([_ev("p1", grounded=True), _ev("p2", grounded=False), _ev("p3", grounded=True)]), min_papers=2)
    assert out is not None
    assert out.evidence_coverage == round(2 / 3, 6)


def test_contradiction_needs_conflicting_spans_from_two_papers() -> None:
    supporting = [_ev("p1", role=EvidenceRole.SHARED_CONTEXT.value), _ev("p2", role=EvidenceRole.SHARED_CONTEXT.value)]
    one_sided = [_ev("p1", role=EvidenceRole.CONFLICTS_WITH_GAP.value)]
    assert assemble(_cand(supporting, gap_type=GapType.CONTRADICTION, conflicting=one_sided), min_papers=2) is None

    both = [
        _ev("p1", role=EvidenceRole.CONFLICTS_WITH_GAP.value),
        _ev("p2", role=EvidenceRole.CONFLICTS_WITH_GAP.value),
    ]
    assert assemble(_cand(supporting, gap_type=GapType.CONTRADICTION, conflicting=both), min_papers=2) is not None
