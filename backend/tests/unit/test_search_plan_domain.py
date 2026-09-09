from __future__ import annotations

from app.domain.candidate import CandidateSource, NormalizedCandidate, SearchPlan
from app.services.normalize.canonical import identity_keys, title_hash


def test_search_plan_defaults() -> None:
    plan = SearchPlan()
    assert plan.keyword_sets == []
    assert plan.expanded_queries == []
    assert plan.perspective_questions == []
    assert plan.citation_anchors == []
    assert plan.generated_by == "fallback"


def test_search_plan_holds_fields() -> None:
    plan = SearchPlan(
        keyword_sets=[["retrieval", "augmented"], ["rag"]],
        expanded_queries=["retrieval augmented generation for QA"],
        perspective_questions=["How does RAG reduce hallucination?"],
        citation_anchors=["10.5555/abc"],
        generated_by="llm",
    )
    assert plan.keyword_sets[0] == ["retrieval", "augmented"]
    assert plan.generated_by == "llm"


def test_identity_keys_prioritise_doi_then_arxiv_then_title() -> None:
    with_doi = NormalizedCandidate(
        title="X", title_hash=title_hash("X"), external_ids={"doi": "10.1/a", "arxiv": "2001.00001"}
    )
    keys = identity_keys(with_doi)
    assert keys[0] == "doi:10.1/a"
    assert "arxiv:2001.00001" in keys
    assert keys[-1] == f"title:{title_hash('X')}"

    title_only = NormalizedCandidate(title="Y", title_hash=title_hash("Y"))
    assert identity_keys(title_only) == [f"title:{title_hash('Y')}"]


def test_primary_identity_key_is_the_first() -> None:
    from app.services.normalize.canonical import primary_identity_key

    cand = NormalizedCandidate(title="X", title_hash=title_hash("X"), external_ids={"arxiv": "2001.00001"})
    assert primary_identity_key(cand) == "arxiv:2001.00001"
    _ = CandidateSource  # keep import used for parity with other domain tests
