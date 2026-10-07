"""Discovery of "papers like this one": Semantic Scholar's recommendations for
the seed (nearest neighbours in SPECTER embedding space, trained on
citation behaviour) and OpenAlex's `related_works` for the seed work. Both
need the seed resolved first (app/services/discovery/resolve.py).

These are the highest-precision related-work sources available for free:
for a survey on agentic AI, S2's recommendations were all agentic-AI papers,
where keyword search pulled in unrelated "literature review" papers. Signals
are left to the semantic scoring pass and the ranking stage. Both sources
are asked at once.
"""

from __future__ import annotations

from app.domain.candidate import DiscoveryStrategy, RawExternalRecord
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
)


class RecommendationStrategy:
    strategy = DiscoveryStrategy.RECOMMENDATION

    async def run(self, ctx: StrategyContext) -> StrategyResult:
        limit = ctx.filters.max_results_per_strategy * 2
        related_ids = [str(w) for w in ((ctx.seed.openalex_work or {}).get("related_works") or [])][:limit]
        s2_id = ctx.seed.s2_paper_id
        if not s2_id and not related_ids:
            return StrategyResult(strategy=self.strategy, notes=["recommendation_no_seed_id"])

        wanted: list[tuple[str, Fetch]] = []
        if s2_id:
            wanted.append(("s2", lambda: SemanticScholarClient(ctx.http).recommendations(s2_id, limit=limit)))
        if related_ids:
            wanted.append(("openalex", lambda: OpenAlexClient(ctx.http).works_by_ids(related_ids)))
        planned: list[tuple[str, Fetch]] = []
        for name, fetch in wanted:
            if ctx.budget.can_call_external():
                ctx.budget.record_external_call()
                planned.append((name, fetch))

        slots: list[Slot] = [None] * len(planned)
        names = [n for n, _ in planned]
        ctx.so_far[self.strategy] = lambda: self._assemble(slots, names)
        await fetch_all(ctx, self.strategy, [f for _, f in planned], slots)
        return self._assemble(slots, names)

    def _assemble(self, slots: list[Slot], names: list[str]) -> StrategyResult:
        result = StrategyResult(strategy=self.strategy)
        for slot, name in zip(slots, names, strict=True):
            if isinstance(slot, ExternalError):
                result.notes.append(f"recommendation_{name}_failed")
            elif slot is not None:
                self._add(result, slot)
        return result

    @staticmethod
    def _add(result: StrategyResult, records: list[RawExternalRecord]) -> None:
        for rec in records:
            key = record_key(rec)
            if key in result.signals:
                continue
            result.records.append(rec)
            result.signals[key] = {}
