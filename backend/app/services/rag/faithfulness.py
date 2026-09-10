"""Faithfulness gate (Architecture §1.1 "RAG faithfulness gate ...
LLM-as-judge (RAGAS lib) ... below threshold -> regenerate once"; Roadmap
Phase 9).

The roadmap's own risk note says to "gate on a cheap heuristic first, full
RAGAS in eval runs". This module is that cheap heuristic: the fraction of
the answer's content tokens that also appear in the retrieved context
(context token-recall). The `ragas` library score is a Phase 16 eval-run
concern (Evaluation Plan §5) and is intentionally not a runtime dependency
here. An optional LLM-judge refinement can be layered later behind the same
`score_faithfulness` signature.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "was", "were",
    "be", "by", "as", "at", "this", "that", "these", "those", "it", "its", "we", "our", "their", "from",
    "which", "can", "may", "not", "no", "than", "then", "also", "such", "using", "used", "use",
}


def _content_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 2}


def score_faithfulness(answer_text: str, context_texts: list[str]) -> float:
    ans = _content_tokens(answer_text)
    if not ans:
        return 1.0
    ctx: set[str] = set()
    for t in context_texts:
        ctx |= _content_tokens(t)
    return round(len(ans & ctx) / len(ans), 6)


def passes(score: float, threshold: float) -> bool:
    return score >= threshold
