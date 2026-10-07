"""Discovery runs its requests at the same time, never in network order
(remediation Phase 8).

Measured on real seeds before this: every strategy asked its sources one
request after another (keyword and query expansion 21-29 s each), citation
looked up ten reference DOIs one at a time and hit its 30 s limit -- and a
strategy stopped by its limit lost everything it had already found (every
real run of 27 September: citation returned nothing). Now a strategy's
requests go out together, each source still pacing its own; records are read
back in the order they were planned, so the result -- and the ranking made
from it -- does not depend on which source answered first; and a strategy
that runs out of time hands over what did arrive.
"""

from __future__ import annotations

import asyncio
import time

import httpx

from app.domain.candidate import CitationRelationship, DiscoveryStrategy, SearchPlan
from app.external.http import ExternalHttpClient
from app.services.discovery.base import (
    DiscoveryFilters,
    SeedView,
    StrategyContext,
    StrategyResult,
    record_key,
)
from app.services.discovery.budget import DiscoveryBudget
from app.services.discovery.citation import CitationStrategy
from app.services.discovery.keyword import KeywordStrategy
from app.services.discovery.recommend import RecommendationStrategy
from app.services.discovery.resolve import resolve_seed
from app.services.discovery.runner import run_discovery_strategies
from app.services.normalize.canonical import title_hash
from app.services.normalize.dedupe import SeedIdentity

_SEED_WORK = {
    "id": "https://openalex.org/W_SEED",
    "doi": "https://doi.org/10.5555/seed",
    "title": "The Seed Paper",
    "referenced_works": ["https://openalex.org/W_REF1"],
    "related_works": ["https://openalex.org/W_REL1"],
}


def _work(wid: str, title: str) -> dict[str, object]:
    return {"id": f"https://openalex.org/{wid}", "doi": f"https://doi.org/10.1/{wid.lower()}", "title": title, "publication_year": 2021}


def _results(*works: dict[str, object]) -> dict[str, object]:
    return {"results": list(works)}


def _ctx(handler, seed: SeedView | None = None, plan: SearchPlan | None = None) -> StrategyContext:  # noqa: ANN001
    return StrategyContext(
        seed=seed or SeedView(paper_id="pap_seed", title="The Seed Paper", doi="10.5555/seed"),
        seed_chunks=[],
        plan=plan or SearchPlan(),
        filters=DiscoveryFilters(max_results_per_strategy=10),
        budget=DiscoveryBudget(),
        http=ExternalHttpClient(transport=httpx.MockTransport(handler)),
    )


def _openalex_search_handler(delays: dict[str, float]):  # noqa: ANN202
    """OpenAlex search answering each query with one work named after it,
    after that query's delay; every other source answers nothing."""

    async def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "openalex.org" in url:
            query = request.url.params.get("search", "")
            await asyncio.sleep(delays.get(query, 0.0))
            return httpx.Response(200, json=_results(_work(f"W_{query.replace(' ', '_')}", f"Result for {query}")))
        if "europepmc" in url:
            return httpx.Response(200, json={"resultList": {"result": []}})
        if "arxiv.org" in url:
            return httpx.Response(200, text='<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>')
        if "semanticscholar.org" in url:
            return httpx.Response(200, json={"data": []})
        if "crossref.org" in url:
            return httpx.Response(200, json={"message": {"items": []}})
        if "dblp.org" in url:
            return httpx.Response(200, json={"result": {"hits": {}}})
        if "core.ac.uk" in url:
            return httpx.Response(200, json={"results": []})
        raise AssertionError(url)

    return h


_PLAN = SearchPlan(keyword_sets=[["alpha"], ["beta"], ["gamma"], ["delta"]])
_QUERIES = ["The Seed Paper", "alpha", "beta", "gamma", "delta"]


def test_a_strategys_requests_go_out_at_the_same_time() -> None:
    ctx = _ctx(_openalex_search_handler({q: 0.3 for q in _QUERIES}), plan=_PLAN)
    started = time.monotonic()
    result = asyncio.run(KeywordStrategy().run(ctx))
    elapsed = time.monotonic() - started
    assert len(result.records) == 5
    assert elapsed < 1.0, f"5 queries of 0.3 s each took {elapsed:.2f}s -- they ran one after another"


def test_records_keep_the_planned_order_whichever_source_answers_first() -> None:
    slow_first = {q: 0.05 * (len(_QUERIES) - i) for i, q in enumerate(_QUERIES)}
    fast_first = {q: 0.05 * i for i, q in enumerate(_QUERIES)}
    a = asyncio.run(KeywordStrategy().run(_ctx(_openalex_search_handler(slow_first), plan=_PLAN)))
    b = asyncio.run(KeywordStrategy().run(_ctx(_openalex_search_handler(fast_first), plan=_PLAN)))
    expected = [f"Result for {q}" for q in _QUERIES]
    assert [r.title for r in a.records] == expected
    assert [r.title for r in b.records] == expected


def test_records_are_announced_as_each_source_answers() -> None:
    ctx = _ctx(_openalex_search_handler({}), plan=_PLAN)
    announced: list[tuple[DiscoveryStrategy, int]] = []
    ctx.on_records = lambda strategy, records: announced.append((strategy, len(records)))
    asyncio.run(KeywordStrategy().run(ctx))
    assert announced and all(s is DiscoveryStrategy.KEYWORD for s, _ in announced)
    assert sum(n for _, n in announced) == 5


def _citation_handler(*, citing_delay: float = 0.0, seen: list[str] | None = None):  # noqa: ANN202
    async def h(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        if "/works/" in url:
            return httpx.Response(200, json=_SEED_WORK)
        params = request.url.params
        filt = params.get("filter", "")
        if filt.startswith("openalex_id:"):
            return httpx.Response(200, json=_results(_work("W_REF1", "Referenced One")))
        if filt.startswith("cites:"):
            await asyncio.sleep(citing_delay)
            return httpx.Response(200, json=_results(_work("W_CITE1", "Citing One")))
        if filt.startswith("doi:"):
            return httpx.Response(200, json=_results(*[_work(f"W_A{i}", f"Anchor {i}") for i in range(len(filt.split("|")))]))
        if "crossref.org" in url:
            return httpx.Response(200, json={"message": {"items": []}})
        if "dblp.org" in url:
            return httpx.Response(200, json={"result": {"hits": {}}})
        if "core.ac.uk" in url:
            return httpx.Response(200, json={"results": []})
        raise AssertionError(url)

    return h


def test_citation_looks_up_every_reference_doi_in_one_request() -> None:
    seen: list[str] = []
    plan = SearchPlan(citation_anchors=["10.1/a0", "10.1/a1", "10.1/a2"])
    result = asyncio.run(CitationStrategy().run(_ctx(_citation_handler(seen=seen), plan=plan)))
    assert sum("filter=doi" in u for u in seen) == 1
    anchors = [r for r in result.records if r.title.startswith("Anchor")]
    assert len(anchors) == 3
    assert all(result.citation_relationships[record_key(r)] is CitationRelationship.CITED_BY_SEED for r in anchors)


def test_a_strategy_stopped_by_its_time_limit_keeps_what_it_found() -> None:
    ctx = _ctx(_citation_handler(citing_delay=5.0))
    out = asyncio.run(
        run_discovery_strategies(
            ctx,
            retrieval_strategies=[CitationStrategy()],
            scoring_strategies=[],
            per_strategy_timeout_s=0.5,
            seed_identity=SeedIdentity(doi="10.5555/seed", title_hash=title_hash("The Seed Paper")),
            filters=DiscoveryFilters(),
        )
    )
    # the references had arrived; the citing works had not
    assert [c.normalized.title for c in out.candidates] == ["Referenced One"]
    assert out.candidates[0].citation_relationship is CitationRelationship.CITED_BY_SEED
    assert DiscoveryStrategy.CITATION in out.strategies_succeeded
    assert DiscoveryStrategy.CITATION in out.strategies_timed_out
    assert "strategy_timeout:citation" in out.warnings
    assert out.status == "partial"


def test_the_seed_is_looked_up_on_both_sources_at_once() -> None:
    async def h(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.4)
        if "openalex.org" in str(request.url):
            return httpx.Response(200, json=_SEED_WORK)
        return httpx.Response(200, json={"paperId": "S2SEED", "title": "The Seed Paper", "externalIds": {"DOI": "10.5555/seed"}})

    ctx = _ctx(h)
    started = time.monotonic()
    asyncio.run(resolve_seed(ctx))
    assert time.monotonic() - started < 0.7
    assert ctx.seed.openalex_work is not None and ctx.seed.s2_paper_id == "S2SEED"


def test_recommendations_ask_both_sources_at_once() -> None:
    async def h(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.4)
        if "openalex.org" in str(request.url):
            return httpx.Response(200, json=_results(_work("W_REL1", "Related One")))
        return httpx.Response(200, json={"recommendedPapers": [{"paperId": "R1", "title": "Recommended One", "externalIds": {}}]})

    ctx = _ctx(h, seed=SeedView(paper_id="pap_seed", title="The Seed Paper", openalex_work=_SEED_WORK, s2_paper_id="S2SEED"))
    started = time.monotonic()
    result = asyncio.run(RecommendationStrategy().run(ctx))
    assert time.monotonic() - started < 0.7
    assert [r.title for r in result.records] == ["Recommended One", "Related One"]  # S2 first, as planned


def test_a_strategy_that_raises_after_finding_nothing_still_fails_cleanly() -> None:
    class Boom:
        strategy = DiscoveryStrategy.KEYWORD

        async def run(self, ctx: StrategyContext) -> StrategyResult:
            raise RuntimeError("boom")

    out = asyncio.run(
        run_discovery_strategies(
            _ctx(_openalex_search_handler({})),
            retrieval_strategies=[Boom()],
            scoring_strategies=[],
            per_strategy_timeout_s=0.5,
            seed_identity=SeedIdentity(),
            filters=DiscoveryFilters(),
        )
    )
    assert out.strategies_failed == [DiscoveryStrategy.KEYWORD]
    assert out.status == "failed"
