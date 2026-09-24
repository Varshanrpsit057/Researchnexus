"""Discovery of "papers like this one": Semantic Scholar's recommendations for
the seed (nearest neighbours in SPECTER embedding space, trained on
citation behaviour) and OpenAlex's `related_works` for the seed work. Both
need the seed resolved first (app/services/discovery/resolve.py).

These are the highest-precision related-work sources available for free:
for a survey on agentic AI, S2's recommendations were all agentic-AI papers,
where keyword search pulled in unrelated "literature review" papers. Signals
are left to the semantic scoring pass and the ranking stage.
"""

from __future__ import annotations

from app.domain.candidate import DiscoveryStrategy, RawExternalRecord
from app.external.http import ExternalError
from app.external.openalex_client import OpenAlexClient
from app.external.semantic_scholar_client import SemanticScholarClient
from app.services.discovery.base import StrategyContext, StrategyResult, record_key


class RecommendationStrategy:
    strategy = DiscoveryStrategy.RECOMMENDATION

    async def run(self, ctx: StrategyContext) -> StrategyResult:
        result = StrategyResult(strategy=self.strategy)
        limit = ctx.filters.max_results_per_strategy * 2
        related_ids = [str(w) for w in ((ctx.seed.openalex_work or {}).get("related_works") or [])][:limit]
        if not ctx.seed.s2_paper_id and not related_ids:
            result.notes.append("recommendation_no_seed_id")
            return result

        if ctx.seed.s2_paper_id and ctx.budget.can_call_external():
            ctx.budget.record_external_call()
            try:
                self._add(result, await SemanticScholarClient(ctx.http).recommendations(ctx.seed.s2_paper_id, limit=limit))
            except ExternalError:
                result.notes.append("recommendation_s2_failed")

        if related_ids and ctx.budget.can_call_external():
            ctx.budget.record_external_call()
            try:
                self._add(result, await OpenAlexClient(ctx.http).works_by_ids(related_ids))
            except ExternalError:
                result.notes.append("recommendation_openalex_failed")
        return result

    @staticmethod
    def _add(result: StrategyResult, records: list[RawExternalRecord]) -> None:
        for rec in records:
            key = record_key(rec)
            if key in result.signals:
                continue
            result.records.append(rec)
            result.signals[key] = {}
