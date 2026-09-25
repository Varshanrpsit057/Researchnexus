"""Verbatim evidence for trail edges, taken from text the system already
holds: the seed's parsed reference list and the target's abstract.

The deterministic rules (rules.py) decide *whether* a relationship holds
from citation facts and ranking signals; left alone, most of them attached
only the target's title as their "evidence span", which is not a claim
anyone can check. Found live: every edge of a real discovery run carried
nothing but a title. This module finds the passage that actually shows the
link:

- when the seed cites the target, the seed's own reference-list entry for
  it (matched on letters and digits only -- PDF extraction often squashes
  the spaces out of reference strings);
- otherwise the target-abstract sentence closest to what the seed is about
  (its research problem or method), by embedding similarity when an
  embedder is available, else by shared content words.

Every span returned is an exact substring of its source, never a paraphrase.
"""

from __future__ import annotations

import re

import numpy as np

from app.domain.profile import SourceSpan
from app.retrieval.embeddings import EmbeddingProvider

MAX_QUOTE = 400
_MIN_TITLE_CHARS = 16  # shorter titles ("Survey") match too much to count as a citation
_MIN_SENTENCE_WORDS = 6
_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")
_WORD_RE = re.compile(r"[a-z0-9]+")
_SUBTITLE_RE = re.compile(r"\s*[:?]\s*")
_STOPWORDS = frozenset(
    [
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "into",
        "is", "it", "its", "of", "on", "or", "that", "the", "their", "this", "to", "was", "we", "were",
        "which", "with", "our", "these", "those", "than", "then", "there", "using", "used", "can",
        "also", "such",
    ]
)


def _letters(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def seed_reference_span(seed_paper_id: str, target_title: str, references: list[dict]) -> SourceSpan | None:
    """The seed's reference entry that cites `target_title`, verbatim."""
    wanted = [_letters(target_title)]
    head = _SUBTITLE_RE.split(target_title, maxsplit=1)[0]
    if head != target_title:
        wanted.append(_letters(head))
    wanted = [w for w in wanted if len(w) >= _MIN_TITLE_CHARS]
    if not wanted:
        return None
    for ref in references:
        raw = str(ref.get("raw_text") or "").strip()
        if not raw:
            continue
        haystack = _letters(raw)
        if any(w in haystack for w in wanted):
            return SourceSpan(paper_id=seed_paper_id, section="References", quote=raw[:MAX_QUOTE])
    return None


def _sentences(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for m in _SENTENCE_RE.finditer(text):
        start, end = m.start(), m.end()
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            spans.append((start, end))
    return spans


def sentence_around(text: str, start: int, end: int) -> tuple[int, int]:
    """The sentence containing text[start:end] (or the match itself)."""
    for s, e in _sentences(text):
        if s <= start < e:
            return s, max(e, end)
    return start, end


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) > 2 and w not in _STOPWORDS}


def best_sentence(
    text: str, queries: list[str], *, embedder: EmbeddingProvider | None = None
) -> tuple[int, int] | None:
    """Offsets of the sentence in `text` closest to any of `queries`, or None
    when there is no full sentence (or, without an embedder, none shares a
    content word with the queries -- an unrelated sentence is not evidence)."""
    queries = [q for q in queries if q and q.strip()]
    candidates = [(s, e) for s, e in _sentences(text) if len(text[s:e].split()) >= _MIN_SENTENCE_WORDS]
    if not candidates or not queries:
        return None

    sentences = [text[s:e] for s, e in candidates]
    if embedder is not None:
        vectors = np.asarray(embedder.embed([*queries, *sentences]), dtype="float32")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.where(norms == 0.0, 1.0, norms)
        scores = (vectors[len(queries) :] @ vectors[: len(queries)].T).max(axis=1)
        best = int(np.argmax(scores))
    else:
        wanted = set().union(*(_content_words(q) for q in queries))
        lexical = [len(wanted & _content_words(s)) / max(1.0, len(_content_words(s)) ** 0.5) for s in sentences]
        best = max(range(len(lexical)), key=lambda i: lexical[i])
        if lexical[best] == 0:
            return None

    start, end = candidates[best]
    return start, min(end, start + MAX_QUOTE)
