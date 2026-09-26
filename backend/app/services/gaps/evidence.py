"""Deterministic evidence assembly (Architecture §1.1 "Gap: evidence
assembly ... >=2 supporting papers or drop"; Roadmap Phase 11).

Runs after the candidate rules, before the LLM. A candidate survives only
if it has supporting `GapEvidence` spans from at least `min_papers`
distinct real papers (and, for `CONTRADICTION`, conflicting spans from
>= 2 papers). `evidence_coverage` is the fraction of supporting papers
whose evidence span is grounded in full text (has a section or character
offset, and the paper's profile was not read from its abstract alone)
rather than an abstract-only mention -- it later down-weights confidence.
"""

from __future__ import annotations

from collections.abc import Collection

from app.domain.gap import GapType
from app.services.gaps.candidates import GapCandidate


def _grounded(span_has_section: bool, span_has_offset: bool) -> bool:
    return span_has_section or span_has_offset


def assemble(
    candidate: GapCandidate, *, min_papers: int, abstract_only: Collection[str] = ()
) -> GapCandidate | None:
    supporting_papers = sorted({e.paper_id for e in candidate.supporting_evidence})
    if len(supporting_papers) < min_papers:
        return None
    if candidate.gap_type is GapType.CONTRADICTION:
        conflicting_papers = {e.paper_id for e in candidate.conflicting_evidence}
        if len(conflicting_papers) < min_papers:
            return None

    grounded = sum(
        1
        for pid in supporting_papers
        if pid not in abstract_only
        and any(
            e.paper_id == pid and _grounded(e.span.section is not None, e.span.char_start is not None)
            for e in candidate.supporting_evidence
        )
    )
    candidate.supporting_papers = supporting_papers
    candidate.evidence_coverage = round(grounded / len(supporting_papers), 6)
    return candidate
