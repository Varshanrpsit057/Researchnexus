"""Stage S2 (part 6): deterministic parse-confidence scoring.

Always computed by rules from measurable signals -- never asserted by an
LLM (review §11, §18; Architecture §3 S2 failure handling). Feeds
`ParsedDocument.parse_confidence`, which the UI surfaces and which the
research-gap pipeline (Phase 11) will use to down-weight low-confidence
evidence -- see the IEEE-limitation traceability note in
docs/architecture/ResearchNexus_Implementation_Architecture.md §9.
"""

from __future__ import annotations

from app.domain.paper import ParseConfidence, RawReference, Section

_MIN_AVG_CHARS_PER_PAGE = 200
_GARBLED_LOW_THRESHOLD = 0.05
_GARBLED_MEDIUM_THRESHOLD = 0.02
_REPLACEMENT_CHAR = "�"


def _garbled_ratio(text: str) -> float:
    if not text:
        return 0.0
    bad = sum(1 for ch in text if ch == _REPLACEMENT_CHAR or (ord(ch) < 32 and ch not in "\n\t"))
    return bad / len(text)


def assess_confidence(
    *,
    page_count: int,
    full_text: str,
    sections: list[Section],
    references: list[RawReference],
    has_text_layer: bool,
) -> tuple[ParseConfidence, list[str]]:
    """Return (confidence, warnings). Deterministic given its inputs."""
    warnings: list[str] = []

    if not has_text_layer or not full_text.strip():
        warnings.append("no extractable text")
        return ParseConfidence.LOW, warnings

    has_real_sections = len(sections) >= 2 and any(not s.is_fallback for s in sections)
    if not has_real_sections:
        warnings.append("section detection failed; using a single fallback body section")

    avg_chars_per_page = len(full_text) / max(page_count, 1)
    garbled = _garbled_ratio(full_text)
    if garbled > _GARBLED_MEDIUM_THRESHOLD:
        warnings.append(f"elevated garbled-character ratio ({garbled:.1%})")
    if not references:
        warnings.append("no references section detected")

    if not has_real_sections or avg_chars_per_page < _MIN_AVG_CHARS_PER_PAGE or garbled > _GARBLED_LOW_THRESHOLD:
        return ParseConfidence.LOW, warnings
    if not references or garbled > _GARBLED_MEDIUM_THRESHOLD:
        return ParseConfidence.MEDIUM, warnings
    return ParseConfidence.HIGH, warnings
