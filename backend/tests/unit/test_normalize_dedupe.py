from __future__ import annotations

from app.domain.candidate import CandidateSource, RawExternalRecord
from app.services.normalize.canonical import title_hash
from app.services.normalize.dedupe import SeedIdentity, dedupe


def _rec(source: CandidateSource, **kw: object) -> RawExternalRecord:
    base: dict[str, object] = {"source": source, "title": "A Paper"}
    base.update(kw)
    return RawExternalRecord(**base)  # type: ignore[arg-type]


def test_arxiv_v1_and_v2_are_merged_via_versionless_id() -> None:
    v1 = _rec(CandidateSource.ARXIV, arxiv_id="http://arxiv.org/abs/2005.11401v1", title="RAG", abstract="short")
    v2 = _rec(CandidateSource.ARXIV, arxiv_id="arXiv:2005.11401v2", title="RAG", abstract="a longer abstract here")
    result = dedupe([v1, v2])
    assert result.raw_count == 2
    assert len(result.candidates) == 1
    assert result.candidates[0].abstract == "a longer abstract here"
    assert result.candidates[0].external_ids["arxiv"] == "2005.11401"


def test_same_doi_across_arxiv_and_openalex_is_merged() -> None:
    a = _rec(CandidateSource.ARXIV, doi="10.5555/abc", title="RAG", arxiv_id="2005.11401")
    b = _rec(CandidateSource.OPENALEX, doi="https://doi.org/10.5555/ABC", title="RAG", venue="NeurIPS", year=2020)
    result = dedupe([a, b])
    assert len(result.candidates) == 1
    merged = result.candidates[0]
    assert merged.external_ids["doi"] == "10.5555/abc"
    assert merged.external_ids["arxiv"] == "2005.11401"
    assert merged.venue == "NeurIPS"
    assert set(merged.sources) == {CandidateSource.ARXIV, CandidateSource.OPENALEX}


def test_title_hash_match_without_ids_is_merged() -> None:
    a = _rec(CandidateSource.SEMANTIC_SCHOLAR, title="Retrieval-Augmented Generation", abstract="x")
    b = _rec(CandidateSource.OPENALEX, title="retrieval augmented generation", abstract="a longer one")
    result = dedupe([a, b])
    assert len(result.candidates) == 1
    assert result.candidates[0].abstract == "a longer one"


def test_near_identical_titles_without_ids_are_flagged_not_merged() -> None:
    # same paper, but one source truncated the title -- close enough to warn
    # a human, not close enough to auto-merge without a shared id.
    a = _rec(CandidateSource.OPENALEX, title="Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks")
    b = _rec(CandidateSource.SEMANTIC_SCHOLAR, title="Retrieval-Augmented Generation for Knowledge-Intensive NLP Task")
    result = dedupe([a, b])
    assert len(result.candidates) == 2
    assert all(cand.possible_duplicate for cand in result.candidates)


def test_moderately_similar_but_distinct_titles_are_not_flagged() -> None:
    a = _rec(CandidateSource.OPENALEX, title="A Survey of Retrieval Augmented Generation Methods")
    b = _rec(CandidateSource.SEMANTIC_SCHOLAR, title="A Survey of Retrieval-Augmented Generation Techniques")
    result = dedupe([a, b])
    assert len(result.candidates) == 2
    assert not any(cand.possible_duplicate for cand in result.candidates)


def test_distinct_papers_are_never_merged() -> None:
    a = _rec(CandidateSource.ARXIV, title="Retrieval-Augmented Generation", doi="10.1/a")
    b = _rec(CandidateSource.ARXIV, title="Dense Passage Retrieval", doi="10.1/b")
    result = dedupe([a, b])
    assert len(result.candidates) == 2
    assert not any(c.possible_duplicate for c in result.candidates)


def test_seed_paper_is_excluded_from_results() -> None:
    seed_doi = "10.1109/bigdata.2024.10825310"
    seed = _rec(CandidateSource.OPENALEX, title="The Seed Paper", doi=seed_doi)
    other = _rec(CandidateSource.ARXIV, title="Some Other Paper", doi="10.1/other")
    result = dedupe([seed, other], seed=SeedIdentity(doi=seed_doi))
    assert [c.title for c in result.candidates] == ["Some Other Paper"]


def test_seed_excluded_by_title_hash_when_no_doi() -> None:
    seed_title = "The Seed Paper Title"
    seed = _rec(CandidateSource.ARXIV, title=seed_title)
    other = _rec(CandidateSource.ARXIV, title="A Different Paper")
    result = dedupe([seed, other], seed=SeedIdentity(title_hash=title_hash(seed_title)))
    assert [c.title for c in result.candidates] == ["A Different Paper"]


def test_counts_are_reported() -> None:
    recs = [
        _rec(CandidateSource.ARXIV, arxiv_id="2005.11401v1", title="RAG"),
        _rec(CandidateSource.OPENALEX, arxiv_id="2005.11401", title="RAG"),
        _rec(CandidateSource.ARXIV, doi="10.1/x", title="Other"),
    ]
    result = dedupe(recs)
    assert result.raw_count == 3
    assert result.deduped_count == 2
