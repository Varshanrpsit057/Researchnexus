"""Deterministic relevance filtering (Architecture §3 S8). Conservative on
purpose: a candidate is only dropped for a concrete, recorded reason
(out-of-window year, missing abstract when required, blank title). Unknown
metadata is never grounds for a drop -- that would silently lose real
papers. Off-topic-threshold filtering needs a relevance score, which is
Phase 6; not done here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.candidate import NormalizedCandidate
from app.services.discovery.base import DiscoveryFilters


@dataclass
class FilterResult:
    kept: list[NormalizedCandidate] = field(default_factory=list)
    dropped: list[tuple[NormalizedCandidate, list[str]]] = field(default_factory=list)


def apply_filters(candidates: list[NormalizedCandidate], filters: DiscoveryFilters) -> FilterResult:
    result = FilterResult()
    for cand in candidates:
        reasons: list[str] = []
        if not cand.title.strip():
            reasons.append("no_title")
        if filters.require_abstract and not (cand.abstract and cand.abstract.strip()):
            reasons.append("no_abstract")
        if filters.min_year is not None and cand.year is not None and cand.year < filters.min_year:
            reasons.append("before_min_year")
        if filters.max_year is not None and cand.year is not None and cand.year > filters.max_year:
            reasons.append("after_max_year")
        (result.dropped.append((cand, reasons)) if reasons else result.kept.append(cand))
    return result
