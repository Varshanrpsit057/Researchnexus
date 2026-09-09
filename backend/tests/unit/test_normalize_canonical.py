from __future__ import annotations

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.services.ingest.pipeline import _title_hash as ingest_title_hash
from app.services.normalize.canonical import (
    normalize_arxiv_id,
    normalize_authors,
    normalize_doi,
    normalize_year,
    title_hash,
    to_normalized,
)


def test_title_hash_ignores_case_punctuation_and_whitespace() -> None:
    a = title_hash("Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks")
    b = title_hash("  retrieval augmented generation for knowledge intensive nlp tasks  ")
    c = title_hash("Retrieval-Augmented   Generation, for Knowledge-Intensive NLP Tasks.")
    assert a == b == c


def test_title_hash_distinguishes_different_titles() -> None:
    assert title_hash("A Study of Transformers") != title_hash("A Study of Transducers")


def test_title_hash_matches_the_ingest_pipeline_hash() -> None:
    # discovered papers must dedupe against ingested ones -- both hashes
    # must agree for a given title (see canonical.py note).
    for t in ["Some Paper Title", "ANOTHER: title, with Punctuation!"]:
        assert title_hash(t) == ingest_title_hash(t)


def test_normalize_doi_strips_prefixes_and_lowercases() -> None:
    assert normalize_doi("https://doi.org/10.1109/BigData.2024.10825310") == "10.1109/bigdata.2024.10825310"
    assert normalize_doi("doi:10.1000/XYZ") == "10.1000/xyz"
    assert normalize_doi("  10.1000/abc  ") == "10.1000/abc"


def test_normalize_doi_rejects_non_dois() -> None:
    assert normalize_doi("") is None
    assert normalize_doi("not-a-doi") is None
    assert normalize_doi(None) is None


def test_normalize_arxiv_id_is_versionless_and_prefix_free() -> None:
    assert normalize_arxiv_id("http://arxiv.org/abs/2005.11401v2") == "2005.11401"
    assert normalize_arxiv_id("arXiv:2005.11401") == "2005.11401"
    assert normalize_arxiv_id("2005.11401v1") == "2005.11401"
    assert normalize_arxiv_id("cs/9901001v3") == "cs/9901001"
    assert normalize_arxiv_id(None) is None


def test_normalize_authors_trims_dedupes_and_drops_blanks() -> None:
    out = normalize_authors(["  Jane  Doe ", "Jane Doe", "", "  ", "John Roe"])
    assert out == ["Jane Doe", "John Roe"]


def test_normalize_year_range_guard() -> None:
    assert normalize_year(2023) == 2023
    assert normalize_year(1600) is None
    assert normalize_year(9999) is None
    assert normalize_year(None) is None


def test_to_normalized_builds_identity_and_sources() -> None:
    rec = RawExternalRecord(
        source=CandidateSource.OPENALEX,
        source_native_id="https://openalex.org/W123",
        doi="https://doi.org/10.5555/ABC",
        title="Retrieval Augmented Generation",
        authors=["A. One", "A. One", "B. Two"],
        year=2020,
        abstract="We propose RAG.",
        venue="NeurIPS",
    )
    cand = to_normalized(rec)
    assert cand.title_hash == title_hash("Retrieval Augmented Generation")
    assert cand.external_ids["doi"] == "10.5555/abc"
    assert cand.external_ids["openalex"] == "W123"
    assert cand.sources == [CandidateSource.OPENALEX]
    assert cand.authors == ["A. One", "B. Two"]
