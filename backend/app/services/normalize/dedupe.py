"""Deduplicate a union of `RawExternalRecord`s from several sources into a
list of merged `NormalizedCandidate`s (Architecture §3 S7; §2 "Dedupe /
merge (DOI -> arXiv id -> title-hash)").

Identity, in priority order: DOI, then versionless arXiv id, then
normalised-title hash. Records that share any one strong key are the same
paper and are merged (merge.py). Records with NO strong id but a
near-identical title are kept separate and both flagged
`possible_duplicate` -- never silently merged (Architecture §3 S7 failure
handling; the dedupe false-merge target is 0, Evaluation Plan §2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.domain.candidate import NormalizedCandidate, RawExternalRecord
from app.services.normalize.canonical import identity_keys, to_normalized
from app.services.normalize.merge import merge_pair

_FUZZY_TITLE_THRESHOLD = 0.92


@dataclass(frozen=True)
class SeedIdentity:
    doi: str | None = None
    arxiv_id: str | None = None
    title_hash: str | None = None


@dataclass
class DedupeResult:
    candidates: list[NormalizedCandidate] = field(default_factory=list)
    raw_count: int = 0
    deduped_count: int = 0


def _matches_seed(cand: NormalizedCandidate, seed: SeedIdentity) -> bool:
    if seed.doi and cand.external_ids.get("doi") == seed.doi:
        return True
    if seed.arxiv_id and cand.external_ids.get("arxiv") == seed.arxiv_id:
        return True
    return bool(seed.title_hash and cand.title_hash == seed.title_hash)


def dedupe(records: list[RawExternalRecord], seed: SeedIdentity | None = None) -> DedupeResult:
    normalized = [to_normalized(r) for r in records]

    # -- union by shared strong key ---------------------------------------------
    groups: list[NormalizedCandidate] = []
    key_to_group: dict[str, int] = {}
    for cand in normalized:
        hit = next((key_to_group[k] for k in identity_keys(cand) if k in key_to_group), None)
        if hit is None:
            groups.append(cand)
            idx = len(groups) - 1
        else:
            groups[hit] = merge_pair(groups[hit], cand)
            idx = hit
        for k in identity_keys(groups[idx]):
            key_to_group[k] = idx

    if seed is not None:
        groups = [g for g in groups if not _matches_seed(g, seed)]

    _flag_fuzzy_duplicates(groups)

    return DedupeResult(candidates=groups, raw_count=len(records), deduped_count=len(groups))


def _flag_fuzzy_duplicates(candidates: list[NormalizedCandidate]) -> None:
    """Second pass: two candidates that were NOT merged (no shared strong
    id) but whose titles are near-identical are each marked
    `possible_duplicate` for a human to resolve."""
    for i in range(len(candidates)):
        for j in range(i + 1, len(candidates)):
            a, b = candidates[i], candidates[j]
            if _share_strong_id(a, b):
                continue
            ratio = SequenceMatcher(None, a.title.lower(), b.title.lower()).ratio()
            if ratio >= _FUZZY_TITLE_THRESHOLD:
                a.possible_duplicate = b.possible_duplicate = True
                a.possible_duplicate_of_title_hash = b.title_hash
                b.possible_duplicate_of_title_hash = a.title_hash


def _share_strong_id(a: NormalizedCandidate, b: NormalizedCandidate) -> bool:
    for key in ("doi", "arxiv"):
        if key in a.external_ids and a.external_ids.get(key) == b.external_ids.get(key):
            return True
    return False
