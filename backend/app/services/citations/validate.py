"""Citation grounding check (Architecture §1.1 "Citation grounding check
(claim -> chunk -> paper -> id) ... Deterministic link + LLM IsSupported? +
ALCE metrics"; Roadmap Phase 9).

Phase 9 ships the deterministic link check: a `Claim` survives only if every
`supporting_chunk_id` resolves to a chunk that was actually retrieved for
this answer, and `supporting_paper_ids` is derived from that map (never from
the LLM). The ALCE-style NLI precision/recall numbers are an eval-run
concern (Evaluation Plan §6) and stay `None` at request time.
"""

from __future__ import annotations

from app.domain.citation import Claim
from app.services.rag._llm import strip_fabricated_references

__all__ = ["link_claims", "strip_fabricated_references"]


def link_claims(
    claims: list[Claim],
    *,
    retrieved_chunk_ids: set[str],
    chunk_to_paper: dict[str, str],
) -> list[Claim]:
    linked: list[Claim] = []
    for c in claims:
        good = [cid for cid in c.supporting_chunk_ids if cid in retrieved_chunk_ids]
        if not good:
            continue  # nothing this claim cites was actually retrieved -> drop it
        linked.append(
            c.model_copy(
                update={
                    "supporting_chunk_ids": good,
                    "supporting_paper_ids": sorted({chunk_to_paper[cid] for cid in good if cid in chunk_to_paper}),
                }
            )
        )
    return linked
