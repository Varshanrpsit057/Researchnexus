"""Merge two `NormalizedCandidate`s that dedupe.py has decided are the same
paper, resolving each field conflict by a fixed, documented rule and
recording every non-trivial choice in `field_provenance` (Roadmap Phase 4:
"metadata conflict resolution" + "provenance/source tracking").

Rules:
- filling a `None` field from the other source is not a conflict (no
  provenance entry);
- `abstract` / `authors`: the more complete value wins (longer text / more
  names); a genuine disagreement is recorded;
- `year` / `venue`: on disagreement the more authoritative source wins
  (Crossref > OpenAlex > Semantic Scholar > arXiv for bibliographic
  metadata), and the loser is recorded;
- `is_preprint` is the AND of both -- if any source has it as a published
  work, the merged record is not a preprint;
- `external_ids` and `sources` are unioned.
"""

from __future__ import annotations

from typing import TypeVar

from app.domain.candidate import CandidateSource, FieldProvenance, NormalizedCandidate

_V = TypeVar("_V")

_SOURCE_AUTHORITY = {
    CandidateSource.CROSSREF: 3,
    CandidateSource.OPENALEX: 2,
    CandidateSource.SEMANTIC_SCHOLAR: 1,
    CandidateSource.EUROPE_PMC: 1,
    CandidateSource.DBLP: 2,  # curated bibliographic records
    CandidateSource.CORE: 1,
    CandidateSource.ARXIV: 0,
}


def _primary_source(cand: NormalizedCandidate) -> CandidateSource:
    return max(cand.sources, key=lambda s: _SOURCE_AUTHORITY[s]) if cand.sources else CandidateSource.ARXIV


def _more_authoritative(a: NormalizedCandidate, b: NormalizedCandidate) -> tuple[NormalizedCandidate, NormalizedCandidate]:
    """Return (winner, loser) by source authority."""
    return (a, b) if _SOURCE_AUTHORITY[_primary_source(a)] >= _SOURCE_AUTHORITY[_primary_source(b)] else (b, a)


def _fp(field: str, winner: NormalizedCandidate, winning_value: object, loser_source: CandidateSource, loser_value: object) -> FieldProvenance:
    return FieldProvenance(
        field=field,
        chosen_source=_primary_source(winner),
        chosen_value=str(winning_value),
        rejected=[f"{loser_source.value}={loser_value}"],
    )


def merge_pair(a: NormalizedCandidate, b: NormalizedCandidate) -> NormalizedCandidate:
    provenance: list[FieldProvenance] = [*a.field_provenance, *b.field_provenance]

    # -- title: keep the longer (usually the un-truncated one) --------------
    title = a.title if len(a.title) >= len(b.title) else b.title
    title_hash = a.title_hash  # identical by construction (dedupe grouped them)

    # -- abstract: more complete wins --------------------------------------------
    abstract = _pick_more_complete("abstract", a, b, a.abstract, b.abstract, provenance, by_length=True)

    # -- authors: longer list wins --------------------------------------------
    if a.authors and b.authors and a.authors != b.authors:
        if len(a.authors) >= len(b.authors):
            authors, loser = a.authors, b
        else:
            authors, loser = b.authors, a
        provenance.append(_fp("authors", a if authors is a.authors else b, len(authors), _primary_source(loser), len(loser.authors)))
    else:
        authors = a.authors or b.authors

    # -- year: authority order on disagreement --------------------------------
    year = _pick_authoritative("year", a, b, a.year, b.year, provenance)

    # -- venue: authority order; a real venue beats None --------------------
    venue = _pick_authoritative("venue", a, b, a.venue, b.venue, provenance)

    # -- url: prefer any non-null (DOI url tends to come from the authoritative source) --
    winner_for_url, loser_for_url = _more_authoritative(a, b)
    url = winner_for_url.url or loser_for_url.url

    merged_ids = {**b.external_ids, **a.external_ids}
    merged_sources = list(dict.fromkeys([*a.sources, *b.sources]))

    return NormalizedCandidate(
        title=title,
        title_hash=title_hash,
        external_ids=merged_ids,
        authors=authors,
        year=year,
        abstract=abstract,
        venue=venue,
        url=url,
        is_preprint=a.is_preprint and b.is_preprint,
        publisher=a.publisher or b.publisher,
        sources=merged_sources,
        field_provenance=provenance,
        possible_duplicate=a.possible_duplicate or b.possible_duplicate,
        possible_duplicate_of_title_hash=a.possible_duplicate_of_title_hash or b.possible_duplicate_of_title_hash,
    )


def _pick_more_complete(
    field: str,
    a: NormalizedCandidate,
    b: NormalizedCandidate,
    av: str | None,
    bv: str | None,
    provenance: list[FieldProvenance],
    *,
    by_length: bool,
) -> str | None:
    if av is None:
        return bv
    if bv is None:
        return av
    if av == bv:
        return av
    if by_length and len(av) >= len(bv):
        provenance.append(_fp(field, a, f"len={len(av)}", _primary_source(b), f"len={len(bv)}"))
        return av
    provenance.append(_fp(field, b, f"len={len(bv)}", _primary_source(a), f"len={len(av)}"))
    return bv


def _pick_authoritative(
    field: str,
    a: NormalizedCandidate,
    b: NormalizedCandidate,
    av: _V | None,
    bv: _V | None,
    provenance: list[FieldProvenance],
) -> _V | None:
    if av is None:
        return bv
    if bv is None:
        return av
    if av == bv:
        return av
    winner, loser = _more_authoritative(a, b)
    winning_value = av if winner is a else bv
    losing_value = bv if winner is a else av
    provenance.append(_fp(field, winner, winning_value, _primary_source(loser), losing_value))
    return winning_value
