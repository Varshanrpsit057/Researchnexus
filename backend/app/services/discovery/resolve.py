"""Resolve the seed paper to its own records on OpenAlex and Semantic
Scholar before discovery starts.

An uploaded PDF often yields no DOI or arXiv id (the parser found none), and
without an id the two most relevant sources of related work -- the seed's
citation neighbourhood and "papers like this one" recommendations -- cannot
run at all. Found live: a seed whose PDF carried no DOI got no citation
candidates, while OpenAlex and S2 both held it (DOI and 87 references
included) under its exact title.

Matching is by exact normalised title only (`title_hash`): a near-miss
title is a different paper, and a wrong match would steer the whole run.
Each lookup is best-effort: any failure only leaves that id unresolved, never
fails the run.
"""

from __future__ import annotations

from app.external.openalex_client import OpenAlexClient
from app.external.semantic_scholar_client import SemanticScholarClient
from app.services.discovery.base import StrategyContext
from app.services.normalize.canonical import normalize_doi, title_hash


def _same_title(a: str | None, b: str | None) -> bool:
    return bool(a and b) and title_hash(a or "") == title_hash(b or "")


async def resolve_seed(ctx: StrategyContext) -> list[str]:
    """Fill `ctx.seed.openalex_work`, `ctx.seed.s2_paper_id` and a missing
    DOI where they can be found. Returns notes for the run's warnings."""
    seed = ctx.seed
    notes: list[str] = []

    if ctx.budget.can_call_external():
        ctx.budget.record_external_call()
        openalex = OpenAlexClient(ctx.http)
        try:
            if seed.doi:
                seed.openalex_work = await openalex.get_work(seed.doi)
            else:
                works = await openalex.search_works(seed.title, per_page=5)
                seed.openalex_work = next((w for w in works if _same_title(w.get("title") or w.get("display_name"), seed.title)), None)
        except Exception:  # noqa: BLE001 - best-effort: an unresolved seed only skips id-based strategies
            notes.append("resolve_openalex_failed")
        if seed.openalex_work is not None and not seed.doi:
            seed.doi = normalize_doi(seed.openalex_work.get("doi"))

    if ctx.budget.can_call_external():
        ctx.budget.record_external_call()
        s2 = SemanticScholarClient(ctx.http)
        try:
            paper = None
            if seed.doi:
                paper = await s2.get_paper(f"DOI:{seed.doi}")
            elif seed.arxiv_id:
                paper = await s2.get_paper(f"ARXIV:{seed.arxiv_id}")
            if paper is None:
                match = await s2.match_title(seed.title)
                paper = match if match and _same_title(match.get("title"), seed.title) else None
            if paper is not None:
                seed.s2_paper_id = paper.get("paperId")
                if not seed.doi:
                    seed.doi = normalize_doi((paper.get("externalIds") or {}).get("DOI"))
        except Exception:  # noqa: BLE001 - best-effort: an unresolved seed only skips id-based strategies
            notes.append("resolve_semantic_scholar_failed")

    if seed.openalex_work is None and seed.s2_paper_id is None:
        notes.append("seed_not_found_on_openalex_or_s2")
    return notes
