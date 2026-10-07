"""1-hop citation discovery (Architecture §3 S6; Data Model §3
`CitationRelationship`), from the seed as resolved by
app/services/discovery/resolve.py:

- OpenAlex: the seed work's `referenced_works` (`cited_by_seed`) and the
  works citing it (`cites_seed`);
- Semantic Scholar: the seed's references and citations, which fill gaps in
  OpenAlex's coverage (and vice versa -- duplicates merge downstream);
- the plan's `citation_anchors` (DOIs pulled from the seed's reference
  list) -> also `cited_by_seed`, looked up together in one request.

The lookups go out at once (remediation Phase 8: one after another, with
the anchors looked up singly, this strategy ran into its 30 s limit on every
real run of 27 September and -- a stopped strategy then losing everything --
returned nothing). Strictly one hop -- the "one extra citation hop" decision
is an orchestrator concern (Architecture §4). A seed resolved on neither
source yields an empty result with a note.
"""

from __future__ import annotations

from typing import Any

from app.domain.candidate import CitationRelationship, DiscoveryStrategy, RawExternalRecord
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

_MAX_ANCHORS = 10


class CitationStrategy:
    strategy = DiscoveryStrategy.CITATION

    async def run(self, ctx: StrategyContext) -> StrategyResult:
        notes: list[str] = []
        openalex = OpenAlexClient(ctx.http)
        # references are the seed's own chosen related work: take up to twice
        # the per-strategy cap; the ranking stage orders them
        limit = ctx.filters.max_results_per_strategy * 2

        seed_work = ctx.seed.openalex_work
        if seed_work is None and ctx.seed.doi:
            seed_work = await self._get_work(ctx, openalex, ctx.seed.doi, notes)
        s2_id = ctx.seed.s2_paper_id
        if seed_work is None and not s2_id:
            return StrategyResult(strategy=self.strategy, notes=[*notes, "citation_no_seed_id"])

        wanted: list[tuple[Fetch, CitationRelationship]] = []
        if seed_work is not None:
            ref_ids = [str(w) for w in (seed_work.get("referenced_works") or [])][:limit]
            wanted.append((lambda: openalex.works_by_ids(ref_ids), CitationRelationship.CITED_BY_SEED))
            seed_id = str(seed_work["id"])
            wanted.append((lambda: openalex.works_citing(seed_id, per_page=limit), CitationRelationship.CITES_SEED))
        if s2_id:
            s2 = SemanticScholarClient(ctx.http)
            wanted.append((lambda: s2.references(s2_id, limit=limit), CitationRelationship.CITED_BY_SEED))
            wanted.append((lambda: s2.citations(s2_id, limit=limit), CitationRelationship.CITES_SEED))
        # the reference-list DOIs cover what the bulk lists above missed
        anchors = ctx.plan.citation_anchors[:_MAX_ANCHORS]
        if anchors:
            wanted.append((lambda: openalex.works_by_dois(anchors), CitationRelationship.CITED_BY_SEED))

        planned: list[tuple[Fetch, CitationRelationship]] = []
        for fetch, relationship in wanted:
            if not ctx.budget.can_call_external():
                notes.append("citation_external_budget")
                break
            ctx.budget.record_external_call()
            planned.append((fetch, relationship))

        slots: list[Slot] = [None] * len(planned)
        relationships = [r for _, r in planned]
        ctx.so_far[self.strategy] = lambda: self._assemble(slots, relationships, notes)
        await fetch_all(ctx, self.strategy, [f for f, _ in planned], slots)
        return self._assemble(slots, relationships, notes)

    def _assemble(self, slots: list[Slot], relationships: list[CitationRelationship], notes: list[str]) -> StrategyResult:
        result = StrategyResult(strategy=self.strategy, notes=list(notes))
        for slot, relationship in zip(slots, relationships, strict=True):
            if isinstance(slot, ExternalError):
                result.notes.append(f"citation_{relationship.value}_failed")
            elif slot is not None:
                for rec in slot:
                    self._add(result, rec, relationship)
        if unanswered(slots):
            result.notes.append(f"citation_unanswered:{unanswered(slots)}")
        return result

    async def _get_work(
        self, ctx: StrategyContext, openalex: OpenAlexClient, id_or_doi: str, notes: list[str]
    ) -> dict[str, Any] | None:
        if not ctx.budget.can_call_external():
            notes.append("citation_external_budget")
            return None
        ctx.budget.record_external_call()
        try:
            return await openalex.get_work(id_or_doi)
        except ExternalError:
            notes.append("citation_lookup_failed")
            return None

    @staticmethod
    def _add(result: StrategyResult, rec: RawExternalRecord, relationship: CitationRelationship) -> None:
        key = record_key(rec)
        if key in result.citation_relationships:
            return
        result.records.append(rec)
        result.citation_relationships[key] = relationship
        result.citation_hops[key] = 1
        result.signals.setdefault(key, {})
