"""Stage S5: turn a `ResearchProfile` into a `SearchPlan` (Architecture §3
S5). One structured LLM call when a BYOK session is available; a
deterministic fallback otherwise or on any LLM failure -- discovery must
still run without an LLM (Architecture §3 S5 failure handling: "LLM failure
-> deterministic fallback ... flag reduced coverage").

`citation_anchors` are DOIs pulled deterministically from the seed's parsed
reference strings (Phase 2 stored them as raw text; there is no resolver
yet, so a DOI regex is the anchor source).
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

from app.domain.candidate import SearchPlan
from app.domain.profile import ResearchProfile
from app.llm.client import ChatMessage, LlmProviderError
from app.llm.schema_repair import build_repair_messages, parse_structured
from app.llm.session import LlmSession

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
_MAX_KEYWORD_SETS = 6
_MAX_EXPANDED = 8
_MAX_TERM_WORDS = 5
_ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9]{1,5}s?$")
_STOPWORDS = frozenset(
    [
        "about", "above", "after", "also", "among", "based", "been", "being", "between", "both",
        "could", "does", "doing", "during", "each", "from", "have", "having", "into", "more", "most",
        "other", "over", "same", "some", "such", "than", "that", "their", "them", "then", "there",
        "these", "they", "this", "those", "through", "toward", "towards", "under", "until", "upon",
        "using", "very", "were", "what", "when", "where", "which", "while", "with", "within", "without",
        "would",
    ]
)


class SearchPlanExtraction(BaseModel):
    keyword_sets: list[list[str]] = Field(default_factory=list)
    expanded_queries: list[str] = Field(default_factory=list)
    perspective_questions: list[str] = Field(default_factory=list)


def extract_reference_dois(raw_reference_texts: list[str]) -> list[str]:
    seen: list[str] = []
    for text in raw_reference_texts:
        for match in _DOI_RE.findall(text):
            doi = match.rstrip(".,;)").lower()
            if doi not in seen:
                seen.append(doi)
    return seen


def _short_phrase(text: str, max_words: int = _MAX_TERM_WORDS) -> str:
    """Reduce a profile value to a short, search-engine-friendly phrase:
    its first few significant (>3 char) words, lowercased. `domain` is
    already phrase-shaped, but `research_problem` and a method/dataset
    description are full sentences -- joining one whole, unbounded
    sentence into a single "keyword" defeats the point of a keyword set,
    and fallback_plan below concatenates a few of these terms again into
    one expanded query. Without this cap, that compounds into an
    unsearchable 40+ word run-on query, which degrades external search to
    matching only common generic words (observed live: a facial-
    recognition paper's fallback plan returned unrelated sentiment-
    analysis and generic ML-survey papers this way, because a query that
    long has nothing distinctive left for arXiv/OpenAlex to match on)."""
    words: list[str] = []
    for word in re.split(r"[^a-zA-Z0-9]+", text):
        # short all-caps acronyms (AI, LLM, RL, GANs) are often the most
        # distinctive term there is; function words never are
        if _ACRONYM_RE.match(word) or (len(word) > 3 and word.lower() not in _STOPWORDS):
            words.append(word.lower())
    return " ".join(words[:max_words])


def _profile_terms(profile: ResearchProfile) -> list[str]:
    """The profile's facets: keywords, then method and dataset names. The
    research problem is left out on purpose -- it is a sentence, and its
    first words are filler ("There is a striking lack of ..."), which is
    exactly what a search engine then matches on."""
    terms = [k.strip().lower() for k in profile.keywords if k.strip()]
    for item in profile.methods.items + profile.datasets.items:
        phrase = _short_phrase(item.value)
        if phrase:
            terms.append(phrase)
    deduped: list[str] = []
    for t in terms:
        if t and t not in deduped:
            deduped.append(t)
    return deduped


def fallback_plan(profile: ResearchProfile, *, citation_anchors: list[str]) -> SearchPlan:
    """Every query pairs the paper's domain with one facet, so a generic
    facet ("structured literature review") only ever searches within the
    domain rather than across all of science."""
    anchor = _short_phrase(profile.domain.value) or _short_phrase(profile.title)
    facets = [t for t in _profile_terms(profile) if t != anchor][:_MAX_KEYWORD_SETS]
    if anchor:
        keyword_sets = [[anchor, f] for f in facets] or [[anchor]]
    else:
        keyword_sets = [[f] for f in facets] or [[profile.title]]
    expanded = [" ".join(group) for group in keyword_sets[:_MAX_EXPANDED] if group]
    return SearchPlan(
        keyword_sets=keyword_sets,
        expanded_queries=expanded,
        perspective_questions=[],
        citation_anchors=citation_anchors,
        generated_by="fallback",
    )


_SYSTEM_PROMPT = (
    "You are a scholarly search strategist. Given a paper's research profile, "
    "produce JSON matching the schema exactly: `keyword_sets` (2-6 short "
    "keyword lists, each a distinct facet of the topic), `expanded_queries` "
    "(2-8 natural-language search queries, including acronym expansions and "
    "synonyms), `perspective_questions` (2-5 questions a related paper might "
    "answer). No prose outside the JSON."
)


def build_search_plan_messages(profile: ResearchProfile) -> list[ChatMessage]:
    facts = (
        f"Domain: {profile.domain.value}\n"
        f"Research problem: {profile.research_problem.value}\n"
        f"Keywords: {', '.join(profile.keywords)}\n"
        f"Methods: {', '.join(i.value for i in profile.methods.items)}\n"
        f"Datasets: {', '.join(i.value for i in profile.datasets.items)}"
    )
    return [ChatMessage(role="system", content=_SYSTEM_PROMPT), ChatMessage(role="user", content=facts)]


async def generate_search_plan(
    profile: ResearchProfile,
    *,
    session: LlmSession | None,
    citation_anchors: list[str],
) -> tuple[SearchPlan, list[str]]:
    if session is None:
        return fallback_plan(profile, citation_anchors=citation_anchors), ["search_plan_fallback_no_llm"]

    messages = build_search_plan_messages(profile)
    try:
        extraction = await _call_with_repair(session, messages)
    except (json.JSONDecodeError, ValidationError, LlmProviderError):
        return fallback_plan(profile, citation_anchors=citation_anchors), ["search_plan_fallback_llm_error"]

    return (
        SearchPlan(
            keyword_sets=[[k for k in group if k.strip()] for group in extraction.keyword_sets if group][:_MAX_KEYWORD_SETS],
            expanded_queries=[q.strip() for q in extraction.expanded_queries if q.strip()][:_MAX_EXPANDED],
            perspective_questions=[q.strip() for q in extraction.perspective_questions if q.strip()],
            citation_anchors=citation_anchors,
            generated_by="llm",
        ),
        [],
    )


async def _call_with_repair(session: LlmSession, messages: list[ChatMessage]) -> SearchPlanExtraction:
    # temperature 0: the same seed is searched with the same queries each run (remediation Phase 8)
    result = await session.client.chat(api_key=session.api_key, model=session.model, messages=messages, temperature=0)
    try:
        return parse_structured(result.content, SearchPlanExtraction)
    except (json.JSONDecodeError, ValidationError) as e:
        repair = build_repair_messages([m.model_dump() for m in messages], result.content, e, SearchPlanExtraction)
        retry = await session.client.chat(
            api_key=session.api_key, model=session.model, messages=[ChatMessage(**m) for m in repair], temperature=0
        )
        return parse_structured(retry.content, SearchPlanExtraction)
