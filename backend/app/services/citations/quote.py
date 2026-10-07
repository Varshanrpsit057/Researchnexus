"""The passage shown for a claim (remediation Phases 11 and 13): the part of
its chunk that supports it, verbatim.

A chunk can run to a few thousand characters; a reader is shown at most
`max_chars` of it. Showing the first `max_chars` -- what chat used to do --
often cut off the very words a claim rests on ("accuracy of about 96%" cited
to a passage whose visible part never says 96). Instead the window is built
around the chunk's sentence that best matches the claim, widened by whole
sentences on both sides, and that sentence is marked. Nothing is rewritten:
the quote is always a contiguous slice of the chunk, and the reader is told
where it was cut.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# a sentence ends at . ! or ? followed by space and a capital, a digit or an opening mark --
# so decimals (93.5%) and abbreviations inside a sentence don't end it
_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[(\"“'‘])")
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = frozenset(
    ["the", "and", "for", "with", "that", "this", "from", "are", "was", "were", "has", "have", "had", "its", "their", "there", "these", "those", "into", "onto", "than", "then", "which", "while", "when", "where", "what", "who", "whom", "whose", "been", "being", "also", "such", "can", "could", "may", "might", "will", "would", "shall", "should", "not", "but", "our", "out", "over", "under", "more", "most", "other", "some", "any", "each", "both", "all", "per", "via", "using", "used", "use", "based"]
)
_NUMBER_WEIGHT = 3  # a figure that matches is the strongest evidence a sentence can share with a claim


@dataclass(frozen=True)
class QuoteWindow:
    quote: str  # a contiguous slice of the chunk, never edited
    cut_before: bool  # the chunk goes on before the quote
    cut_after: bool  # ...and after it
    highlight: tuple[int, int] | None  # the sentence that best supports the claim, as offsets into `quote`


def _sentences(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    start = 0
    for m in _BOUNDARY.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(s, e) for s, e in spans if e > s]


def _weights(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for tok in _TOKEN.findall(text.lower()):
        if tok[0].isdigit():
            out[tok] = _NUMBER_WEIGHT
        elif len(tok) > 2 and tok not in _STOP:
            out[tok] = 1
    return out


def quote_window(text: str, claim: str, *, max_chars: int) -> QuoteWindow:
    """The verbatim window of `text` that best shows what supports `claim`."""
    text = text.strip()
    spans = _sentences(text)
    wanted = _weights(claim)
    scores = [sum(w for tok, w in wanted.items() if tok in _weights(text[s:e])) for s, e in spans]
    best = max(range(len(spans)), key=lambda i: (scores[i], -i)) if spans and max(scores, default=0) > 0 else None

    if len(text) <= max_chars:
        return QuoteWindow(text, False, False, spans[best] if best is not None else None)
    if best is None:
        return QuoteWindow(text[:max_chars], False, True, None)

    s, e = spans[best]
    if e - s >= max_chars:  # one sentence longer than the window: show its start
        return QuoteWindow(text[s : s + max_chars], s > 0, True, (0, max_chars))
    lo = hi = best
    while True:  # widen by whole sentences, what follows first
        grew = False
        if hi + 1 < len(spans) and spans[hi + 1][1] - spans[lo][0] <= max_chars:
            hi += 1
            grew = True
        if lo > 0 and spans[hi][1] - spans[lo - 1][0] <= max_chars:
            lo -= 1
            grew = True
        if not grew:
            break
    start, end = spans[lo][0], spans[hi][1]
    return QuoteWindow(text[start:end], start > 0, end < len(text), (s - start, e - start))
