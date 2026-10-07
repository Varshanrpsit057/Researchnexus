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

import asyncio

from app.external.openalex_client import OpenAlexClient
from app.external.semantic_scholar_client import SemanticScholarClient
from app.services.discovery.base import StrategyContext
from app.services.normalize.canonical import normalize_doi, title_hash


def _same_title(a: str | None, b: str | None) -> bool:
    return bool(a and b) and title_hash(a or "") == title_hash(b or "")


async def resolve_seed(ctx: StrategyContext) -> list[str]:
    """Fill `ctx.seed.openalex_work`, `ctx.seed.s2_paper_id` and a missing
    DOI where they can be found. Returns notes for the run's warnings.

    Both sources are asked at once, each by the seed's own ids when it has
    them, else by its title. A seed without a DOI that OpenAlex then supplies
    one for, but that Semantic Scholar's title match missed, is asked for on
    Semantic Scholar once more by that DOI -- the exact lookup."""
    seed = ctx.seed
    had_doi = bool(seed.doi)
    lookups = []
    if ctx.budget.can_call_external():
        ctx.budget.record_external_call()
        lookups.append(_openalex(ctx))
    if ctx.budget.can_call_external():
        ctx.budget.record_external_call()
        lookups.append(_semantic_scholar(ctx, by_doi=None))
    ok = dict(await asyncio.gather(*lookups))

    openalex_doi = normalize_doi((seed.openalex_work or {}).get("doi"))
    if not had_doi and openalex_doi:
        seed.doi = openalex_doi
        if seed.s2_paper_id is None and ctx.budget.can_call_external():
            ctx.budget.record_external_call()
            ok.update([await _semantic_scholar(ctx, by_doi=openalex_doi)])
    if not seed.doi:
        seed.doi = normalize_doi(((seed.s2_record or {}).get("externalIds") or {}).get("DOI"))

    notes = [f"resolve_{source}_failed" for source, fine in ok.items() if not fine]
    if seed.openalex_work is None and seed.s2_paper_id is None:
        notes.append("seed_not_found_on_openalex_or_s2")
    return notes


async def _openalex(ctx: StrategyContext) -> tuple[str, bool]:
    """(source, whether it could be asked): a seed that isn't there is an answer, not a failure."""
    seed = ctx.seed
    openalex = OpenAlexClient(ctx.http)
    try:
        if seed.doi:
            seed.openalex_work = await openalex.get_work(seed.doi)
        else:
            works = await openalex.search_works(seed.title, per_page=5)
            seed.openalex_work = next((w for w in works if _same_title(w.get("title") or w.get("display_name"), seed.title)), None)
    except Exception:  # noqa: BLE001 - best-effort: an unresolved seed only skips id-based strategies
        return "openalex", False
    return "openalex", True


async def _semantic_scholar(ctx: StrategyContext, *, by_doi: str | None) -> tuple[str, bool]:
    seed = ctx.seed
    s2 = SemanticScholarClient(ctx.http)
    try:
        paper = None
        if by_doi or seed.doi:
            paper = await s2.get_paper(f"DOI:{by_doi or seed.doi}")
        elif seed.arxiv_id:
            paper = await s2.get_paper(f"ARXIV:{seed.arxiv_id}")
        if paper is None and by_doi is None:
            match = await s2.match_title(seed.title)
            paper = match if match and _same_title(match.get("title"), seed.title) else None
        if paper is not None:
            seed.s2_paper_id = paper.get("paperId")
            seed.s2_record = paper
    except Exception:  # noqa: BLE001 - best-effort: an unresolved seed only skips id-based strategies
        return "semantic_scholar", False
    return "semantic_scholar", True
