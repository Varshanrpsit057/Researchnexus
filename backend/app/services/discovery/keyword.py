"""Lexical discovery strategies: `keyword` (facet keyword lists from the
SearchPlan) and `query_expansion` (the plan's expanded / perspective
queries). Both hit arXiv + OpenAlex and score each hit with a simple
query-term overlap score in [0, 1] -- a deliberate stand-in for BM25 (no
`rank-bm25` dependency; the real corpus-BM25 index is deferred with
`scripts/build_corpus_index.py`).

Per-source failure is isolated: if arXiv is down the OpenAlex hits still
come back (Architecture §3 S6 failure handling).
"""

from __future__ import annotations

import re

from app.domain.candidate import DiscoveryStrategy, RawExternalRecord, SearchPlan
from app.external.arxiv_client import ArxivClient
from app.external.http import ExternalError
from app.external.openalex_client import OpenAlexClient
from app.services.discovery.base import StrategyContext, StrategyResult, record_key

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def keyword_score(query_terms: list[str], record: RawExternalRecord) -> float:
    if not query_terms:
        return 0.0
    doc = set(_tokens(f"{record.title} {record.abstract or ''}"))
    matched = sum(1 for t in query_terms if t in doc)
    return round(matched / len(query_terms), 4)


class _LexicalStrategy:
    strategy: DiscoveryStrategy

    def _queries(self, plan: SearchPlan) -> list[str]:  # pragma: no cover - overridden
        raise NotImplementedError

    async def run(self, ctx: StrategyContext) -> StrategyResult:
        result = StrategyResult(strategy=self.strategy)
        queries = [q for q in self._queries(ctx.plan) if q.strip()]
        if not queries:
            result.notes.append(f"{self.strategy.value}_no_queries")
            return result

        all_query_terms = _tokens(" ".join(queries))
        clients = (ArxivClient(ctx.http), OpenAlexClient(ctx.http))
        errors = 0
        attempted = 0

        for query in queries:
            if ctx.budget.expired():
                result.notes.append(f"{self.strategy.value}_deadline")
                break
            stop = False
            for client in clients:
                if not ctx.budget.can_call_external():
                    result.notes.append(f"{self.strategy.value}_external_budget")
                    stop = True
                    break
                ctx.budget.record_external_call()
                attempted += 1
                try:
                    hits = await client.search(query, max_results=ctx.filters.max_results_per_strategy)
                except ExternalError:
                    errors += 1
                    continue
                for rec in hits:
                    key = record_key(rec)
                    if key in result.signals:
                        continue
                    result.records.append(rec)
                    result.signals[key] = {"keyword_score": keyword_score(all_query_terms, rec)}
            if stop:
                break

        if not result.records and attempted and errors == attempted:
            result.notes.append(f"{self.strategy.value}_all_sources_failed")
        return result


class KeywordStrategy(_LexicalStrategy):
    strategy = DiscoveryStrategy.KEYWORD

    def _queries(self, plan: SearchPlan) -> list[str]:
        return [" ".join(group) for group in plan.keyword_sets if group]


class QueryExpansionStrategy(_LexicalStrategy):
    strategy = DiscoveryStrategy.QUERY_EXPANSION

    def _queries(self, plan: SearchPlan) -> list[str]:
        return [*plan.expanded_queries, *plan.perspective_questions]
