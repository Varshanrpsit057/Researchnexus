from __future__ import annotations

import asyncio

import httpx

from app.domain.candidate import CitationRelationship, DiscoveryStrategy, SearchPlan
from app.external.http import ExternalHttpClient
from app.services.discovery.base import DiscoveryFilters, SeedView, StrategyContext
from app.services.discovery.budget import DiscoveryBudget
from app.services.discovery.citation import CitationStrategy

_SEED_WORK = {
    "id": "https://openalex.org/W_SEED",
    "doi": "https://doi.org/10.5555/seed",
    "title": "The Seed Paper",
    "publication_year": 2021,
    "referenced_works": ["https://openalex.org/W_REF1", "https://openalex.org/W_REF2"],
}

_REFERENCED = {
    "results": [
        {"id": "https://openalex.org/W_REF1", "doi": "https://doi.org/10.1/ref1", "title": "Referenced One", "publication_year": 2018},
        {"id": "https://openalex.org/W_REF2", "doi": "https://doi.org/10.1/ref2", "title": "Referenced Two", "publication_year": 2019},
    ]
}

_CITING = {
    "results": [
        {"id": "https://openalex.org/W_CITE1", "doi": "https://doi.org/10.1/cite1", "title": "A Later Paper Citing Seed", "publication_year": 2023}
    ]
}


def _handler() -> httpx.MockTransport:
    def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/works/" in url and "doi.org/10.5555/seed" in url:
            return httpx.Response(200, json=_SEED_WORK)
        if "filter=openalex_id" in url or "filter=ids.openalex" in url:
            return httpx.Response(200, json=_REFERENCED)
        if "filter=cites" in url:
            return httpx.Response(200, json=_CITING)
        if "filter=doi" in url:  # the reference-list DOIs, looked up together
            return httpx.Response(
                200,
                json={"results": [{"id": "https://openalex.org/W_ANCHOR", "doi": "https://doi.org/10.1/anchor", "title": "Anchor Ref", "publication_year": 2017}]},
            )
        raise AssertionError(f"unexpected url: {url}")

    return httpx.MockTransport(h)


async def _no_sleep(_s: float) -> None:
    return None


def _ctx(seed: SeedView, plan: SearchPlan) -> StrategyContext:
    return StrategyContext(
        seed=seed,
        seed_chunks=[],
        plan=plan,
        filters=DiscoveryFilters(max_results_per_strategy=10),
        budget=DiscoveryBudget(),
        http=ExternalHttpClient(transport=_handler(), sleep=_no_sleep),
    )


def test_citation_strategy_returns_referenced_and_citing_papers_with_relationships() -> None:
    ctx = _ctx(SeedView(paper_id="pap_seed", title="The Seed Paper", doi="10.5555/seed"), SearchPlan())
    result = asyncio.run(CitationStrategy().run(ctx))

    assert result.strategy == DiscoveryStrategy.CITATION
    by_title = {r.title: r for r in result.records}
    assert {"Referenced One", "Referenced Two", "A Later Paper Citing Seed"} <= set(by_title)

    from app.services.discovery.base import record_key

    ref_key = record_key(by_title["Referenced One"])
    cite_key = record_key(by_title["A Later Paper Citing Seed"])
    assert result.citation_relationships[ref_key] == CitationRelationship.CITED_BY_SEED
    assert result.citation_relationships[cite_key] == CitationRelationship.CITES_SEED
    assert result.citation_hops[ref_key] == 1


def test_citation_strategy_resolves_plan_citation_anchors() -> None:
    ctx = _ctx(
        SeedView(paper_id="pap_seed", title="The Seed Paper", doi="10.5555/seed"),
        SearchPlan(citation_anchors=["10.1/anchor"]),
    )
    result = asyncio.run(CitationStrategy().run(ctx))
    assert any(r.title == "Anchor Ref" for r in result.records)


def test_citation_strategy_is_empty_without_a_seed_doi() -> None:
    ctx = _ctx(SeedView(paper_id="pap_seed", title="No DOI Seed", doi=None), SearchPlan())
    result = asyncio.run(CitationStrategy().run(ctx))
    assert result.records == []
    assert "citation_no_seed_id" in result.notes
