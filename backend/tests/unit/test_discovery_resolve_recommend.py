"""Seed resolution, "papers like this one", and S2-backed citations."""

from __future__ import annotations

import asyncio

import httpx

from app.domain.candidate import CitationRelationship, DiscoveryStrategy, SearchPlan
from app.external.http import ExternalHttpClient
from app.services.discovery.base import DiscoveryFilters, SeedView, StrategyContext, record_key
from app.services.discovery.budget import DiscoveryBudget
from app.services.discovery.citation import CitationStrategy
from app.services.discovery.recommend import RecommendationStrategy
from app.services.discovery.resolve import resolve_seed

TITLE = "Agentic AI: A Comprehensive Survey of Technologies, Applications, and Societal Implications"


async def _no_sleep(_s: float) -> None:
    return None


def _paper(pid: str, title: str) -> dict[str, object]:
    return {"paperId": pid, "title": title, "year": 2025, "abstract": f"{title} abstract", "externalIds": {}}


def _work(wid: str, title: str) -> dict[str, object]:
    return {"id": f"https://openalex.org/{wid}", "title": title, "publication_year": 2025}


def _ctx(handler, seed: SeedView) -> StrategyContext:  # type: ignore[no-untyped-def]
    return StrategyContext(
        seed=seed,
        seed_chunks=[],
        plan=SearchPlan(),
        filters=DiscoveryFilters(max_results_per_strategy=10),
        budget=DiscoveryBudget(),
        http=ExternalHttpClient(transport=httpx.MockTransport(handler), sleep=_no_sleep),
    )


def test_resolve_finds_a_doi_less_seed_by_exact_title_on_both_sources() -> None:
    def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openalex.org/works" in url:
            return httpx.Response(
                200,
                json={
                    "results": [
                        _work("W9", "Agentic AI: something else entirely"),
                        {**_work("W1", TITLE), "doi": "https://doi.org/10.1109/ACCESS.2025.3585609", "related_works": []},
                    ]
                },
            )
        if "paper/DOI:" in url:  # S2 lookup by the DOI OpenAlex just supplied
            return httpx.Response(200, json={"paperId": "s2seed", "title": TITLE, "externalIds": {}})
        raise AssertionError(url)

    ctx = _ctx(h, SeedView(paper_id="pap_seed", title=TITLE))
    notes = asyncio.run(resolve_seed(ctx))
    assert notes == []
    assert ctx.seed.openalex_work is not None and ctx.seed.openalex_work["id"].endswith("W1")
    assert ctx.seed.doi == "10.1109/access.2025.3585609"
    assert ctx.seed.s2_paper_id == "s2seed"


def test_resolve_rejects_a_near_miss_title() -> None:
    def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openalex.org/works" in url:
            return httpx.Response(200, json={"results": [_work("W2", "Agentic AI: A Survey")]})
        if "search/match" in url:
            return httpx.Response(200, json={"data": [{"paperId": "other", "title": "Agentic AI: A Survey"}]})
        raise AssertionError(url)

    ctx = _ctx(h, SeedView(paper_id="pap_seed", title=TITLE))
    notes = asyncio.run(resolve_seed(ctx))
    assert ctx.seed.openalex_work is None and ctx.seed.s2_paper_id is None and ctx.seed.doi is None
    assert "seed_not_found_on_openalex_or_s2" in notes


def test_resolution_failure_never_fails_the_run() -> None:
    def h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    ctx = _ctx(h, SeedView(paper_id="pap_seed", title=TITLE))
    notes = asyncio.run(resolve_seed(ctx))
    assert "resolve_openalex_failed" in notes and "resolve_semantic_scholar_failed" in notes


def test_recommendations_come_from_s2_and_openalex_related_works() -> None:
    def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "recommendations/v1/papers/forpaper/s2seed" in url:
            return httpx.Response(200, json={"recommendedPapers": [_paper("r1", "Towards safe agentic AI")]})
        if "openalex.org/works" in url and "openalex_id" in request.url.params.get("filter", ""):
            return httpx.Response(200, json={"results": [_work("W5", "Agentic AI in healthcare")]})
        raise AssertionError(url)

    seed = SeedView(paper_id="pap_seed", title=TITLE, s2_paper_id="s2seed", openalex_work={"id": "W1", "related_works": ["https://openalex.org/W5"]})
    result = asyncio.run(RecommendationStrategy().run(_ctx(h, seed)))
    assert result.strategy == DiscoveryStrategy.RECOMMENDATION
    assert {r.title for r in result.records} == {"Towards safe agentic AI", "Agentic AI in healthcare"}


def test_recommendations_need_a_resolved_seed() -> None:
    def h(request: httpx.Request) -> httpx.Response:
        raise AssertionError(str(request.url))

    result = asyncio.run(RecommendationStrategy().run(_ctx(h, SeedView(paper_id="pap_seed", title=TITLE))))
    assert result.records == [] and result.notes == ["recommendation_no_seed_id"]


def test_citations_run_from_an_s2_only_seed_and_tag_the_direction() -> None:
    def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.split("?")[0].endswith("/paper/s2seed/references"):
            return httpx.Response(200, json={"data": [{"citedPaper": _paper("ref1", "A cited foundation")}]})
        if url.split("?")[0].endswith("/paper/s2seed/citations"):
            return httpx.Response(200, json={"data": [{"citingPaper": _paper("cit1", "A paper citing the survey")}]})
        raise AssertionError(url)

    seed = SeedView(paper_id="pap_seed", title=TITLE, s2_paper_id="s2seed")
    result = asyncio.run(CitationStrategy().run(_ctx(h, seed)))
    by_title = {r.title: result.citation_relationships[record_key(r)] for r in result.records}
    assert by_title == {
        "A cited foundation": CitationRelationship.CITED_BY_SEED,
        "A paper citing the survey": CitationRelationship.CITES_SEED,
    }
