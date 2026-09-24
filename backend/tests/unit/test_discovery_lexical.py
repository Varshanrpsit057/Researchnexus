from __future__ import annotations

import asyncio

import httpx

from app.domain.candidate import DiscoveryStrategy, SearchPlan
from app.external.http import ExternalHttpClient
from app.services.discovery.base import DiscoveryFilters, SeedView, StrategyContext
from app.services.discovery.budget import DiscoveryBudget
from app.services.discovery.keyword import KeywordStrategy, QueryExpansionStrategy

_ARXIV_FEED = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/2005.11401v1</id><published>2020-05-01T00:00:00Z</published>
    <title>Retrieval Augmented Generation</title><summary>retrieval augmented generation for qa</summary>
    <author><name>P. Lewis</name></author>
  </entry>
</feed>"""

_OPENALEX = {
    "results": [
        {
            "id": "https://openalex.org/W1",
            "doi": "https://doi.org/10.5555/dpr",
            "title": "Dense Passage Retrieval",
            "publication_year": 2020,
            "authorships": [{"author": {"display_name": "V. Karpukhin"}}],
            "abstract_inverted_index": {"dense": [0], "retrieval": [1], "qa": [2]},
        }
    ]
}


_EUROPE_PMC = {
    "resultList": {
        "result": [
            {
                "id": "123",
                "source": "MED",
                "title": "Retrieval for clinical question answering.",
                "authorString": "A. Author, B. Author.",
                "pubYear": "2021",
                "abstractText": "We study <i>retrieval</i> for clinical QA.",
            }
        ]
    }
}

_S2 = {"data": [{"paperId": "s2x", "title": "Seed-like Paper", "year": 2022, "externalIds": {}}]}


async def _no_sleep(_seconds: float) -> None:
    return None


def _ctx(handler: httpx.MockTransport, plan: SearchPlan, **budget_kw: object) -> StrategyContext:
    return StrategyContext(
        seed=SeedView(paper_id="pap_seed", title="Seed", abstract="seed abstract"),
        seed_chunks=[],
        plan=plan,
        filters=DiscoveryFilters(max_results_per_strategy=10),
        budget=DiscoveryBudget(**budget_kw),  # type: ignore[arg-type]
        http=ExternalHttpClient(transport=handler, sleep=_no_sleep),
    )


def _handler(calls: dict[str, int], seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls["n"] = calls.get("n", 0) + 1
        if seen is not None:
            seen.append(request)
        if "arxiv.org" in url:
            return httpx.Response(200, text=_ARXIV_FEED)
        if "openalex.org" in url:
            return httpx.Response(200, json=_OPENALEX)
        if "europepmc" in url:
            return httpx.Response(200, json=_EUROPE_PMC)
        if "semanticscholar.org" in url:
            return httpx.Response(200, json=_S2)
        raise AssertionError(url)

    return httpx.MockTransport(h)


def test_keyword_strategy_queries_every_source_and_tags_results() -> None:
    calls: dict[str, int] = {}
    ctx = _ctx(_handler(calls), SearchPlan(keyword_sets=[["retrieval", "augmented", "generation"]]))
    result = asyncio.run(KeywordStrategy().run(ctx))

    assert result.strategy == DiscoveryStrategy.KEYWORD
    titles = {r.title for r in result.records}
    assert "Retrieval Augmented Generation" in titles  # arXiv
    assert "Dense Passage Retrieval" in titles  # OpenAlex
    assert "Retrieval for clinical question answering" in titles  # Europe PMC, markup and trailing dot cleaned
    assert "Seed-like Paper" in titles  # Semantic Scholar (title query)
    for key, sig in result.signals.items():
        assert 0.0 <= sig["keyword_score"] <= 1.0
        assert key  # every record carries a signal keyed by its identity


def test_keyword_strategy_searches_the_seed_title_first_and_phrase_exact_on_arxiv() -> None:
    seen: list[httpx.Request] = []
    ctx = _ctx(_handler({}, seen), SearchPlan(keyword_sets=[["agentic ai systems", "structured literature review"]]))
    ctx.seed.title = "Agentic AI: A Comprehensive Survey of Technologies"
    asyncio.run(KeywordStrategy().run(ctx))

    arxiv = [r.url.params["search_query"] for r in seen if "arxiv.org" in str(r.url)]
    # the main title phrase (before the subtitle) first, then the facet set,
    # every multi-word term required as an exact phrase
    assert arxiv == ['all:"Agentic AI"', 'all:"agentic ai systems" AND all:"structured literature review"']
    s2 = [r.url.params["query"] for r in seen if "semanticscholar.org" in str(r.url)]
    assert s2 == ["Agentic AI: A Comprehensive Survey of Technologies"]  # S2 keyword search: the title query only


def test_query_expansion_strategy_uses_expanded_queries() -> None:
    calls: dict[str, int] = {}
    plan = SearchPlan(keyword_sets=[["ignored"]], expanded_queries=["retrieval augmented generation for QA"])
    ctx = _ctx(_handler(calls), plan)
    result = asyncio.run(QueryExpansionStrategy().run(ctx))
    assert result.strategy == DiscoveryStrategy.QUERY_EXPANSION
    assert result.records  # ran the expanded query


def test_lexical_strategy_returns_empty_when_upstreams_all_fail() -> None:
    def h(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    ctx = _ctx(httpx.MockTransport(h), SearchPlan(keyword_sets=[["x"]]), max_external_calls=10)
    result = asyncio.run(KeywordStrategy().run(ctx))
    assert result.records == []
    assert "keyword" in " ".join(result.notes) or result.notes  # a note explains the empty result


def test_lexical_strategy_stops_when_external_call_budget_is_exhausted() -> None:
    calls: dict[str, int] = {}
    ctx = _ctx(_handler(calls), SearchPlan(keyword_sets=[["a"], ["b"], ["c"], ["d"]]), max_external_calls=5)
    asyncio.run(KeywordStrategy().run(ctx))
    assert calls["n"] == 5  # never exceeded the budget
