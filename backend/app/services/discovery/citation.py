"""1-hop citation discovery (Architecture §3 S6; Data Model §3
`CitationRelationship`), from the seed as resolved by
app/services/discovery/resolve.py:

- OpenAlex: the seed work's `referenced_works` (`cited_by_seed`) and the
  works citing it (`cites_seed`);
- Semantic Scholar: the seed's references and citations, which fill gaps in
  OpenAlex's coverage (and vice versa -- duplicates merge downstream);
- the plan's `citation_anchors` (DOIs pulled from the seed's reference
  list) -> also `cited_by_seed`.

Strictly one hop -- the "one extra citation hop" decision is an
orchestrator concern (Architecture §4). A seed resolved on neither source
yields an empty result with a note.
"""

from __future__ import annotations

from collections.abc import Awaitable, Coroutine
from typing import Any

from app.domain.candidate import CitationRelationship, DiscoveryStrategy, RawExternalRecord
from app.external.http import ExternalError
from app.external.openalex_client import OpenAlexClient
from app.external.semantic_scholar_client import SemanticScholarClient
from app.services.discovery.base import StrategyContext, StrategyResult, record_key


class CitationStrategy:
    strategy = DiscoveryStrategy.CITATION

    async def run(self, ctx: StrategyContext) -> StrategyResult:
        result = StrategyResult(strategy=self.strategy)
        openalex = OpenAlexClient(ctx.http)
        # references are the seed's own chosen related work: take up to twice
        # the per-strategy cap; the ranking stage orders them
        limit = ctx.filters.max_results_per_strategy * 2

        seed_work = ctx.seed.openalex_work
        if seed_work is None and ctx.seed.doi:
            seed_work = await self._get_work(ctx, openalex, ctx.seed.doi, result)
        s2_id = ctx.seed.s2_paper_id
        if seed_work is None and not s2_id:
            result.notes.append("citation_no_seed_id")
            return result

        if seed_work is not None:
            ref_ids = [str(w) for w in (seed_work.get("referenced_works") or [])][:limit]
            await self._collect(ctx, result, openalex.works_by_ids(ref_ids), CitationRelationship.CITED_BY_SEED)
            await self._collect(
                ctx,
                result,
                openalex.works_citing(str(seed_work["id"]), per_page=limit),
                CitationRelationship.CITES_SEED,
            )
        if s2_id:
            s2 = SemanticScholarClient(ctx.http)
            await self._collect(ctx, result, s2.references(s2_id, limit=limit), CitationRelationship.CITED_BY_SEED)
            await self._collect(ctx, result, s2.citations(s2_id, limit=limit), CitationRelationship.CITES_SEED)

        # each anchor is its own lookup; a handful covers what the bulk
        # reference lists above missed without spending the whole budget
        for doi in ctx.plan.citation_anchors[:10]:
            work = await self._get_work(ctx, openalex, doi, result)
            if work is not None:
                self._add(result, OpenAlexClient._work_to_record(work), CitationRelationship.CITED_BY_SEED)
        return result

    async def _get_work(
        self, ctx: StrategyContext, openalex: OpenAlexClient, id_or_doi: str, result: StrategyResult
    ) -> dict[str, Any] | None:
        if not ctx.budget.can_call_external():
            result.notes.append("citation_external_budget")
            return None
        ctx.budget.record_external_call()
        try:
            return await openalex.get_work(id_or_doi)
        except ExternalError:
            result.notes.append("citation_lookup_failed")
            return None

    async def _collect(
        self,
        ctx: StrategyContext,
        result: StrategyResult,
        coro: Awaitable[list[RawExternalRecord]],
        relationship: CitationRelationship,
    ) -> None:
        if not ctx.budget.can_call_external():
            result.notes.append("citation_external_budget")
            if isinstance(coro, Coroutine):
                coro.close()  # never started; close it rather than leave it un-awaited
            return
        ctx.budget.record_external_call()
        try:
            records = await coro
        except ExternalError:
            result.notes.append(f"citation_{relationship.value}_failed")
            return
        for rec in records:
            self._add(result, rec, relationship)

    @staticmethod
    def _add(result: StrategyResult, rec: RawExternalRecord, relationship: CitationRelationship) -> None:
        key = record_key(rec)
        if key in result.citation_relationships:
            return
        result.records.append(rec)
        result.citation_relationships[key] = relationship
        result.citation_hops[key] = 1
        result.signals.setdefault(key, {})
