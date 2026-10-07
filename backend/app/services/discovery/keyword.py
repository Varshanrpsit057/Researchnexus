"""Lexical discovery strategies: `keyword` and `query_expansion`.

Queries:
- `keyword`: the seed's own main title phrase first -- the most specific
  query there is ("Agentic AI" for "Agentic AI: A Comprehensive Survey
  of ...") -- then the plan's facet keyword sets;
- `query_expansion`: the plan's expanded / perspective queries.

Sources per query: OpenAlex always; arXiv with every phrase required
exactly (a bare `all:agentic systems survey` lets arXiv match any single
word, which is how unrelated papers crowded in); Europe PMC, for the life
sciences the others reach poorly; Semantic Scholar's keyword search for the
title query only -- its strict rate limit is kept for the recommendation and
citation calls, which are worth more.

Each hit carries a query-term overlap `keyword_score` in [0, 1] as a raw
signal; relevance ordering is the ranking stage's job (semantic similarity).
Per-source failure is isolated: if arXiv is down the other hits still come
back (Architecture §3 S6 failure handling). Every query goes to every source
at once (remediation Phase 8 -- they used to go one after another, 21-29 s
a strategy on real seeds); the hits are read back in query order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import partial

from app.domain.candidate import DiscoveryStrategy, RawExternalRecord
from app.external.arxiv_client import ArxivClient
from app.external.core_client import CoreClient
from app.external.crossref_client import CrossrefClient
from app.external.dblp_client import DblpClient
from app.external.europepmc_client import EuropePmcClient
from app.external.http import ExternalError
from app.external.openalex_client import OpenAlexClient
from app.external.semantic_scholar_client import SemanticScholarClient
from app.services.discovery.base import (
    Fetch,
    Slot,
    StrategyContext,
    StrategyResult,
    fetch_all,
    record_key,
    unanswered,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SUBTITLE_RE = re.compile(r"\s*(?::|\?|\s[-–—]\s)\s*")
_MAX_KEYWORD_QUERIES = 4
_MAX_EXPANDED_QUERIES = 6


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def keyword_score(query_terms: list[str], record: RawExternalRecord) -> float:
    if not query_terms:
        return 0.0
    doc = set(_tokens(f"{record.title} {record.abstract or ''}"))
    matched = sum(1 for t in query_terms if t in doc)
    return round(matched / len(query_terms), 4)


def main_title_phrase(title: str) -> str:
    """The title before its subtitle ("Agentic AI: A Survey" -> "Agentic AI");
    the whole title when there is no subtitle or the head is one word."""
    head = _SUBTITLE_RE.split(title.strip(), maxsplit=1)[0].strip()
    return head if len(head.split()) >= 2 else title.strip()


def _quoted(phrases: list[str]) -> str:
    return " AND ".join(f'"{p}"' if " " in p else p for p in (p.replace('"', " ").strip() for p in phrases) if p)


@dataclass
class LexicalQuery:
    text: str  # free-text query for OpenAlex
    phrases: list[str] = field(default_factory=list)  # arXiv phrase-exact search; [] skips arXiv
    s2_text: str | None = None  # Semantic Scholar keyword search; None skips it
    dblp: bool = False  # DBLP's computer-science index (gently paced)
    core: bool = False  # CORE's open-access repositories (a small keyless quota)

    def europe_pmc(self) -> str:
        return _quoted(self.phrases) if self.phrases else self.text


class _LexicalStrategy:
    strategy: DiscoveryStrategy

    def _queries(self, ctx: StrategyContext) -> list[LexicalQuery]:  # pragma: no cover - overridden
        raise NotImplementedError

    async def run(self, ctx: StrategyContext) -> StrategyResult:
        queries = [q for q in self._queries(ctx) if q.text.strip()]
        if not queries:
            return StrategyResult(strategy=self.strategy, notes=[f"{self.strategy.value}_no_queries"])

        terms = _tokens(" ".join(q.text for q in queries))
        openalex, arxiv = OpenAlexClient(ctx.http), ArxivClient(ctx.http)
        europe_pmc, s2 = EuropePmcClient(ctx.http), SemanticScholarClient(ctx.http)
        crossref, dblp, core = CrossrefClient(ctx.http), DblpClient(ctx.http), CoreClient(ctx.http)
        n = ctx.filters.max_results_per_strategy

        # every query to every source is planned first, in a fixed order, and
        # the external-call budget is spent as it is planned
        planned: list[Fetch] = []
        notes: list[str] = []
        for query in queries:
            calls: list[Fetch] = [
                partial(openalex.search, query.text, max_results=n),
                partial(europe_pmc.search, query.europe_pmc(), max_results=n),
                # publishers' own records (IEEE, Springer, ACM, Elsevier deposit theirs in Crossref)
                partial(crossref.search, query.text, max_results=n),
            ]
            if query.phrases:
                calls.append(partial(arxiv.search_phrases, query.phrases, max_results=n))
            if query.s2_text:
                calls.append(partial(s2.search, query.s2_text, max_results=n))
            if query.dblp:
                calls.append(partial(dblp.search, query.text, max_results=n))
            if query.core:
                calls.append(partial(core.search, query.text, max_results=n))
            for call in calls:
                if not ctx.budget.can_call_external():
                    notes.append(f"{self.strategy.value}_external_budget")
                    break
                ctx.budget.record_external_call()
                planned.append(call)
            if notes:
                break

        slots: list[Slot] = [None] * len(planned)
        ctx.so_far[self.strategy] = lambda: self._assemble(slots, terms, notes)
        await fetch_all(ctx, self.strategy, planned, slots)
        return self._assemble(slots, terms, notes)

    def _assemble(self, slots: list[Slot], terms: list[str], notes: list[str]) -> StrategyResult:
        result = StrategyResult(strategy=self.strategy, notes=list(notes))
        for slot in slots:
            if not isinstance(slot, list):
                continue
            for rec in slot:
                key = record_key(rec)
                if key in result.signals:
                    continue
                result.records.append(rec)
                result.signals[key] = {"keyword_score": keyword_score(terms, rec)}
        answered = [s for s in slots if s is not None]
        if not result.records and answered and all(isinstance(s, ExternalError) for s in answered):
            result.notes.append(f"{self.strategy.value}_all_sources_failed")
        if unanswered(slots):
            result.notes.append(f"{self.strategy.value}_unanswered:{unanswered(slots)}")
        return result


class KeywordStrategy(_LexicalStrategy):
    strategy = DiscoveryStrategy.KEYWORD

    def _queries(self, ctx: StrategyContext) -> list[LexicalQuery]:
        head = main_title_phrase(ctx.seed.title)
        queries = [LexicalQuery(text=head, phrases=[head], s2_text=ctx.seed.title, dblp=True, core=True)] if head else []
        for i, group in enumerate(ctx.plan.keyword_sets[:_MAX_KEYWORD_QUERIES]):
            terms = [t for t in group if t.strip()]
            if terms:
                queries.append(LexicalQuery(text=" ".join(terms), phrases=terms, dblp=i == 0))
        return queries


class QueryExpansionStrategy(_LexicalStrategy):
    strategy = DiscoveryStrategy.QUERY_EXPANSION

    def _queries(self, ctx: StrategyContext) -> list[LexicalQuery]:
        texts = [*ctx.plan.expanded_queries, *ctx.plan.perspective_questions][:_MAX_EXPANDED_QUERIES]
        return [LexicalQuery(text=t) for t in texts]
