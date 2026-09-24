from __future__ import annotations

import asyncio

import httpx

from app.domain.candidate import (
    CandidateSource,
    CitationRelationship,
    DiscoveryStrategy,
    RawExternalRecord,
    SearchPlan,
)
from app.external.http import ExternalHttpClient
from app.services.discovery.base import (
    DiscoveryFilters,
    SeedView,
    StrategyContext,
    StrategyResult,
    record_key,
)
from app.services.discovery.budget import DiscoveryBudget
from app.services.discovery.runner import RunnerOutput, run_discovery_strategies
from app.services.normalize.canonical import title_hash
from app.services.normalize.dedupe import SeedIdentity


def _rec(title: str, *, doi: str | None = None, arxiv: str | None = None, abstract: str = "abstract") -> RawExternalRecord:
    return RawExternalRecord(source=CandidateSource.OPENALEX, doi=doi, arxiv_id=arxiv, title=title, abstract=abstract, year=2022)


class _FakeStrategy:
    def __init__(self, strategy: DiscoveryStrategy, result: StrategyResult | None = None, *, raises: BaseException | None = None, hang: bool = False) -> None:
        self.strategy = strategy
        self._result = result or StrategyResult(strategy=strategy)
        self._raises = raises
        self._hang = hang

    async def run(self, ctx: StrategyContext) -> StrategyResult:
        if self._hang:
            await asyncio.sleep(10)
        if self._raises is not None:
            raise self._raises
        return self._result


def _ctx(**budget_kw: object) -> StrategyContext:
    return StrategyContext(
        seed=SeedView(paper_id="pap_seed", title="The Seed Paper", abstract="seed abstract", doi="10.5555/seed"),
        seed_chunks=[],
        plan=SearchPlan(),
        filters=DiscoveryFilters(),
        budget=DiscoveryBudget(**budget_kw),  # type: ignore[arg-type]
        http=ExternalHttpClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))),
    )


def _seed_identity() -> SeedIdentity:
    return SeedIdentity(doi="10.5555/seed", title_hash=title_hash("The Seed Paper"))


def _run(retrieval: list[object], scoring: list[object] | None = None, *, ctx: StrategyContext | None = None) -> RunnerOutput:
    return asyncio.run(
        run_discovery_strategies(
            ctx or _ctx(),
            retrieval_strategies=retrieval,  # type: ignore[arg-type]
            scoring_strategies=scoring or [],  # type: ignore[arg-type]
            per_strategy_timeout_s=0.2,
            seed_identity=_seed_identity(),
            filters=DiscoveryFilters(),
        )
    )


def test_union_across_strategies_with_cross_strategy_dedup() -> None:
    kw = StrategyResult(strategy=DiscoveryStrategy.KEYWORD)
    r1 = _rec("Paper One", doi="10.1/a")
    kw.records = [r1, _rec("Paper Two", doi="10.1/b")]
    kw.signals = {"doi:10.1/a": {"keyword_score": 0.8}, "doi:10.1/b": {"keyword_score": 0.5}}

    qe = StrategyResult(strategy=DiscoveryStrategy.QUERY_EXPANSION)
    qe.records = [_rec("Paper One", doi="10.1/a"), _rec("Paper Three", doi="10.1/c")]  # Paper One also found here
    qe.signals = {"doi:10.1/a": {"keyword_score": 0.9}, "doi:10.1/c": {"keyword_score": 0.4}}

    out = _run([_FakeStrategy(DiscoveryStrategy.KEYWORD, kw), _FakeStrategy(DiscoveryStrategy.QUERY_EXPANSION, qe)])

    assert out.count_raw == 4
    assert out.count_after_dedupe == 3
    by_title = {c.normalized.title: c for c in out.candidates}
    assert set(by_title) == {"Paper One", "Paper Two", "Paper Three"}
    # Paper One was found by both strategies
    assert set(by_title["Paper One"].discovery_methods) == {DiscoveryStrategy.KEYWORD, DiscoveryStrategy.QUERY_EXPANSION}
    # signal is the max across the strategies that computed it
    assert by_title["Paper One"].raw_signals.keyword_score == 0.9
    assert out.status == "succeeded"


def test_one_strategy_raising_does_not_stop_the_others() -> None:
    ok = StrategyResult(strategy=DiscoveryStrategy.KEYWORD)
    ok.records = [_rec("Survivor", doi="10.1/ok")]
    out = _run(
        [
            _FakeStrategy(DiscoveryStrategy.KEYWORD, ok),
            _FakeStrategy(DiscoveryStrategy.CITATION, raises=RuntimeError("boom")),
        ]
    )
    assert [c.normalized.title for c in out.candidates] == ["Survivor"]
    assert DiscoveryStrategy.KEYWORD in out.strategies_succeeded
    assert DiscoveryStrategy.CITATION in out.strategies_failed
    assert out.status == "partial"


def test_a_strategy_that_hangs_is_timed_out_and_marked_failed() -> None:
    ok = StrategyResult(strategy=DiscoveryStrategy.KEYWORD)
    ok.records = [_rec("Fast", doi="10.1/fast")]
    out = _run(
        [_FakeStrategy(DiscoveryStrategy.KEYWORD, ok), _FakeStrategy(DiscoveryStrategy.SEMANTIC, hang=True)]
    )
    assert DiscoveryStrategy.SEMANTIC in out.strategies_failed
    assert "strategy_timeout:semantic" in out.warnings
    assert out.status == "partial"


def test_all_strategies_failing_yields_status_failed() -> None:
    out = _run(
        [
            _FakeStrategy(DiscoveryStrategy.KEYWORD, raises=RuntimeError("x")),
            _FakeStrategy(DiscoveryStrategy.CITATION, raises=RuntimeError("y")),
        ]
    )
    assert out.candidates == []
    assert out.status == "failed"
    assert set(out.strategies_failed) == {DiscoveryStrategy.KEYWORD, DiscoveryStrategy.CITATION}


def test_seed_paper_is_excluded_from_candidates() -> None:
    kw = StrategyResult(strategy=DiscoveryStrategy.KEYWORD)
    kw.records = [_rec("The Seed Paper", doi="10.5555/seed"), _rec("A Real Candidate", doi="10.1/real")]
    out = _run([_FakeStrategy(DiscoveryStrategy.KEYWORD, kw)])
    assert [c.normalized.title for c in out.candidates] == ["A Real Candidate"]


def test_scoring_strategy_signals_merge_onto_retrieved_candidates() -> None:
    kw = StrategyResult(strategy=DiscoveryStrategy.KEYWORD)
    r = _rec("Scored Paper", doi="10.1/s")
    kw.records = [r]
    kw.signals = {"doi:10.1/s": {"keyword_score": 0.3}}

    sem = StrategyResult(strategy=DiscoveryStrategy.SEMANTIC)
    sem.records = [r]
    sem.signals = {"doi:10.1/s": {"semantic_score": 0.77}}

    out = _run([_FakeStrategy(DiscoveryStrategy.KEYWORD, kw)], [_FakeStrategy(DiscoveryStrategy.SEMANTIC, sem)])
    cand = out.candidates[0]
    assert cand.raw_signals.keyword_score == 0.3
    assert cand.raw_signals.semantic_score == 0.77
    assert set(cand.discovery_methods) == {DiscoveryStrategy.KEYWORD, DiscoveryStrategy.SEMANTIC}


def test_citation_relationship_is_carried_through() -> None:
    cit = StrategyResult(strategy=DiscoveryStrategy.CITATION)
    r = _rec("Cited Work", doi="10.1/cited")
    cit.records = [r]
    cit.citation_relationships = {"doi:10.1/cited": CitationRelationship.CITED_BY_SEED}
    cit.citation_hops = {"doi:10.1/cited": 1}
    out = _run([_FakeStrategy(DiscoveryStrategy.CITATION, cit)])
    assert out.candidates[0].citation_relationship == CitationRelationship.CITED_BY_SEED
    assert out.candidates[0].citation_hops == 1


def test_budget_total_cap_truncates_and_marks_partial() -> None:
    kw = StrategyResult(strategy=DiscoveryStrategy.KEYWORD)
    kw.records = [_rec(f"Paper {i}", doi=f"10.1/{i}") for i in range(10)]
    out = _run([_FakeStrategy(DiscoveryStrategy.KEYWORD, kw)], ctx=_ctx(max_total_candidates=4))
    assert len(out.candidates) == 4
    assert "budget_truncated" in out.warnings
    assert out.status == "partial"


def test_truncation_keeps_the_best_evidenced_candidates_and_counts_what_was_kept() -> None:
    # The cap applies before any ranking, so it must not cut blindly in
    # discovery order: a paper the seed's recommendations or citations
    # produced, or that several strategies found, outranks a single keyword hit.
    kw = StrategyResult(strategy=DiscoveryStrategy.KEYWORD)
    kw.records = [_rec(f"Keyword Hit {i}", doi=f"10.1/k{i}") for i in range(5)] + [_rec("Found Twice", doi="10.1/twice")]
    qe = StrategyResult(strategy=DiscoveryStrategy.QUERY_EXPANSION)
    qe.records = [_rec("Found Twice", doi="10.1/twice")]
    rec = StrategyResult(strategy=DiscoveryStrategy.RECOMMENDATION)
    rec.records = [_rec("Recommended For The Seed", doi="10.1/rec")]
    for result in (kw, qe, rec):  # as real strategies do: every record they return is attributed to them
        result.signals = {record_key(r): {} for r in result.records}
    out = _run(
        [
            _FakeStrategy(DiscoveryStrategy.KEYWORD, kw),
            _FakeStrategy(DiscoveryStrategy.QUERY_EXPANSION, qe),
            _FakeStrategy(DiscoveryStrategy.RECOMMENDATION, rec),
        ],
        ctx=_ctx(max_total_candidates=3),
    )
    titles = [c.normalized.title for c in out.candidates]
    assert len(titles) == 3
    assert "Found Twice" in titles
    assert "Recommended For The Seed" in titles
    assert out.count_after_filter == 3  # counts what was kept, not the pre-cap pool
