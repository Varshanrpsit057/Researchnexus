"""Deterministic verification that a quote the LLM produced actually exists
in a paper's own text -- the guard that keeps an LLM from inventing
evidence (Roadmap Phase 7: "The LLM must not invent evidence"). Same
technique as app/services/profile/provenance_check.py (stdlib difflib, no
new dependency), kept independent so the trail package doesn't depend on
the profile package.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.domain.profile import SourceSpan

_WHITESPACE_RE = re.compile(r"\s+")
_FUZZY_THRESHOLD = 0.9
_MAX_QUOTE = 400


def _norm(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().lower()


def verify_quote_in_text(quote: str, text: str) -> bool:
    q, t = quote.strip(), text.strip()
    if not q or not t:
        return False
    if _norm(q) in _norm(t):
        return True
    matcher = SequenceMatcher(None, _norm(q), _norm(t), autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return (matched / len(_norm(q))) >= _FUZZY_THRESHOLD


def find_span(quote: str, text: str, *, paper_id: str, section: str | None = None, page: int | None = None) -> SourceSpan | None:
    q = quote.strip()
    if not q or not text:
        return None
    idx = text.find(q)
    if idx >= 0:
        return SourceSpan(
            paper_id=paper_id, section=section, page=page, char_start=idx, char_end=idx + len(q), quote=q[:_MAX_QUOTE]
        )
    if verify_quote_in_text(q, text):
        # matched only after whitespace/case normalisation -- keep the quote,
        # drop the exact offsets rather than guess them.
        return SourceSpan(paper_id=paper_id, section=section, page=page, quote=q[:_MAX_QUOTE])
    return None
