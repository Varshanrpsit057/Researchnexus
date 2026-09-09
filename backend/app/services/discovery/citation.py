"""1-hop citation discovery (Architecture §3 S6; Data Model §3
`CitationRelationship`). Resolves the seed on OpenAlex by DOI, then:

- its `referenced_works`  -> candidates the seed CITES  (`cited_by_seed`)
- works that cite the seed -> candidates that CITE the seed (`cites_seed`)
- the plan's `citation_anchors` (DOIs pulled from the seed's reference
  list) -> also `cited_by_seed`

Strictly one hop -- the "one extra citation hop" decision is an
orchestrator concern (Architecture §4) and is out of Phase 5 scope. A seed
with no DOI yields an empty result with a note (arXiv-only seeds would need
a DOI-resolution step, deferred).
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any

from app.domain.candidate import CitationRelationship, DiscoveryStrategy, RawExternalRecord
from app.external.http import ExternalError
from app.external.openalex_client import OpenAlexClient
from app.services.discovery.base import StrategyContext, StrategyResult, record_key


class CitationStrategy:
    strategy = DiscoveryStrategy.CITATION

    async def run(self, ctx: StrategyContext) -> StrategyResult:
        result = StrategyResult(strategy=self.strategy)
        if not ctx.seed.doi:
            result.notes.append("citation_no_seed_id")
            return result

        openalex = OpenAlexClient(ctx.http)
        limit = ctx.filters.max_results_per_strategy

        seed_work = await self._get_work(ctx, openalex, ctx.seed.doi, result)
        if seed_work is None:
            result.notes.append("citation_seed_not_on_openalex")
            return result

        ref_ids = [str(w) for w in (seed_work.get("referenced_works") or [])][:limit]
        await self._collect(ctx, result, openalex.works_by_ids(ref_ids), CitationRelationship.CITED_BY_SEED)
        await self._collect(
            ctx,
            result,
            openalex.works_citing(str(seed_work["id"]), per_page=limit),
            CitationRelationship.CITES_SEED,
        )

        for doi in ctx.plan.citation_anchors[:limit]:
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
