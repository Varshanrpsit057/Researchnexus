"""Answerability gate (Architecture §4 `AnswerabilityGate`; Roadmap Phase 9
"answerability gating ... 'I don't know'").

Phase 9 scope: the deterministic half only -- if the contextual filter kept
fewer than `min_chunks` chunks, the workspace does not hold enough evidence,
so we return "not answerable" + a suggestion and the pipeline skips
generation entirely (no generation tokens billed, per the API spec). The
RA-FSM LLM refinement (Relevance -> Confidence -> Knowledge) belongs with
the orchestrator and is out of scope here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.rag import FilteredChunk

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z-]{2,}")
_STOP = {
    "what", "which", "how", "why", "does", "do", "did", "is", "are", "the", "and", "for", "with",
    "this", "that", "these", "those", "from", "about", "can", "could", "would", "should", "was",
    "were", "has", "have", "had", "into", "than", "then", "there", "their",
}


def _keywords(query: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for w in _WORD_RE.findall(query):
        lw = w.lower()
        if lw in _STOP or lw in seen:
            continue
        seen.add(lw)
        out.append(w)
    return out


@dataclass(frozen=True)
class Answerability:
    answerable: bool
    suggestion: str | None = None
    kept_chunks: int = 0


def assess(query: str, filtered: list[FilteredChunk], *, min_chunks: int) -> Answerability:
    kept = [c for c in filtered if c.kept]
    if len(kept) >= min_chunks:
        return Answerability(answerable=True, kept_chunks=len(kept))
    kws = _keywords(query)
    suggestion = (
        f"Not enough in this workspace. Add papers about: {', '.join(kws[:4])}."
        if kws
        else "Not enough in this workspace. Add more papers relevant to this question."
    )
    return Answerability(answerable=False, suggestion=suggestion, kept_chunks=len(kept))
