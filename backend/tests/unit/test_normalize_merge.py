from __future__ import annotations

from app.domain.candidate import CandidateSource, NormalizedCandidate
from app.services.normalize.merge import merge_pair


def _c(source: CandidateSource, **kw: object) -> NormalizedCandidate:
    base: dict[str, object] = {"title": "A Paper", "title_hash": "h", "sources": [source]}
    base.update(kw)
    return NormalizedCandidate(**base)  # type: ignore[arg-type]


def test_merge_prefers_the_longer_abstract() -> None:
    a = _c(CandidateSource.ARXIV, abstract="Short.")
    b = _c(CandidateSource.OPENALEX, abstract="A considerably longer and more complete abstract.")
    merged = merge_pair(a, b)
    assert merged.abstract == "A considerably longer and more complete abstract."


def test_merge_prefers_the_longer_author_list() -> None:
    a = _c(CandidateSource.SEMANTIC_SCHOLAR, authors=["A. One"])
    b = _c(CandidateSource.CROSSREF, authors=["A. One", "B. Two", "C. Three"])
    merged = merge_pair(a, b)
    assert merged.authors == ["A. One", "B. Two", "C. Three"]


def test_merge_preprint_and_published_keeps_journal_venue_and_clears_preprint_flag() -> None:
    preprint = _c(CandidateSource.ARXIV, venue=None, is_preprint=True)
    published = _c(CandidateSource.CROSSREF, venue="IEEE Transactions on X", is_preprint=False)
    merged = merge_pair(preprint, published)
    assert merged.venue == "IEEE Transactions on X"
    assert merged.is_preprint is False
    assert set(merged.sources) == {CandidateSource.ARXIV, CandidateSource.CROSSREF}
    # filling venue from None is not a disagreement -> no conflict recorded
    assert [fp.field for fp in merged.field_provenance] == []


def test_merge_records_venue_disagreement_between_two_real_venues() -> None:
    a = _c(CandidateSource.SEMANTIC_SCHOLAR, venue="ArXiv preprint")
    b = _c(CandidateSource.CROSSREF, venue="IEEE Transactions on X")
    merged = merge_pair(a, b)
    assert merged.venue == "IEEE Transactions on X"
    venue_fp = next(fp for fp in merged.field_provenance if fp.field == "venue")
    assert venue_fp.chosen_source == CandidateSource.CROSSREF


def test_merge_year_conflict_prefers_more_authoritative_source_and_records_it() -> None:
    arxiv = _c(CandidateSource.ARXIV, year=2019)
    crossref = _c(CandidateSource.CROSSREF, year=2020)
    merged = merge_pair(arxiv, crossref)
    assert merged.year == 2020
    year_fp = next(fp for fp in merged.field_provenance if fp.field == "year")
    assert year_fp.chosen_source == CandidateSource.CROSSREF
    assert "arxiv=2019" in year_fp.rejected


def test_merge_unions_external_ids_and_sources() -> None:
    a = _c(CandidateSource.ARXIV, external_ids={"arxiv": "2005.11401"})
    b = _c(CandidateSource.OPENALEX, external_ids={"doi": "10.5555/abc", "openalex": "W1"})
    merged = merge_pair(a, b)
    assert merged.external_ids == {"arxiv": "2005.11401", "doi": "10.5555/abc", "openalex": "W1"}
    assert set(merged.sources) == {CandidateSource.ARXIV, CandidateSource.OPENALEX}


def test_merge_without_conflicts_records_no_field_provenance() -> None:
    a = _c(CandidateSource.ARXIV, abstract="Same text.", authors=["A. One"], year=2021)
    b = _c(CandidateSource.OPENALEX, abstract="Same text.", authors=["A. One"], year=2021)
    merged = merge_pair(a, b)
    assert merged.field_provenance == []


def test_merge_fills_a_null_field_from_the_other_without_marking_a_conflict() -> None:
    a = _c(CandidateSource.ARXIV, year=None, venue=None)
    b = _c(CandidateSource.OPENALEX, year=2022, venue="NeurIPS")
    merged = merge_pair(a, b)
    assert merged.year == 2022
    assert merged.venue == "NeurIPS"
    assert merged.field_provenance == []
