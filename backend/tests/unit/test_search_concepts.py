from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.profile import Confidence, ProfileField, ProfileList, ResearchProfile
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.search_concepts.concept_generator import (
    extract_reference_dois,
    fallback_plan,
    generate_search_plan,
)


def _profile(**kw: object) -> ResearchProfile:
    base: dict[str, object] = {
        "profile_id": "prof_1",
        "paper_id": "pap_1",
        "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP",
        "abstract": "We propose RAG.",
        "domain": ProfileField(value="Natural Language Processing"),
        "research_problem": ProfileField(value="reducing hallucination in knowledge-intensive question answering"),
        "keywords": ["retrieval augmented generation", "rag", "open domain qa"],
        "methods": ProfileList(items=[ProfileField(value="dense retrieval"), ProfileField(value="seq2seq")]),
        "datasets": ProfileList(items=[ProfileField(value="Natural Questions")]),
        "extraction_confidence": Confidence.HIGH,
    }
    base.update(kw)
    return ResearchProfile(**base)  # type: ignore[arg-type]


def test_extract_reference_dois_pulls_and_dedupes() -> None:
    refs = [
        "[1] Lewis et al. Retrieval-Augmented Generation. https://doi.org/10.5555/ABC.123",
        "[2] Karpukhin et al. DPR. doi:10.18653/v1/2020.emnlp-main.550",
        "[3] Some paper with no DOI at all.",
        "[4] Duplicate. 10.5555/abc.123",
    ]
    dois = extract_reference_dois(refs)
    assert dois == ["10.5555/abc.123", "10.18653/v1/2020.emnlp-main.550"]


def test_fallback_plan_is_non_empty_from_a_profile() -> None:
    plan = fallback_plan(_profile(), citation_anchors=["10.5555/abc"])
    assert plan.generated_by == "fallback"
    assert plan.keyword_sets  # non-empty
    assert any("retrieval augmented generation" in kw for group in plan.keyword_sets for kw in group)
    assert plan.expanded_queries  # a naive expansion still produces something
    assert plan.citation_anchors == ["10.5555/abc"]


def test_fallback_plan_keeps_queries_short_for_a_profile_with_no_keywords() -> None:
    # Observed live: a real profile with empty `keywords` and long,
    # sentence-shaped `research_problem`/`methods` values produced a 40+
    # word run-on "expanded query" (every value joined whole, then several
    # of those joined again) -- a query that long returns unrelated
    # results from a real search API, because it has nothing distinctive
    # left to match on. Every query must stay short enough to still be a
    # real search query, and the profile's own significant words (not
    # generic filler) must be the ones that survive.
    profile = _profile(
        keywords=[],
        domain=ProfileField(value="Facial recognition-based attendance system"),
        research_problem=ProfileField(
            value=(
                "Improving facial recognition accuracy for attendance tracking, especially in "
                "large-group settings and under non-ideal conditions, while addressing false "
                "positives and scalability."
            )
        ),
        methods=ProfileList(
            items=[
                ProfileField(
                    value=(
                        "Combination of the FaceNet model with an enhanced facial database, where "
                        "multiple images of each individual were collected using a 180-degree video "
                        "capture method."
                    )
                )
            ]
        ),
        datasets=ProfileList(items=[]),
    )
    plan = fallback_plan(profile, citation_anchors=[])
    for query in plan.expanded_queries:
        assert len(query.split()) <= 20, f"query too long to be a real search query: {query!r}"
    joined = " ".join(plan.expanded_queries)
    assert "facial" in joined
    assert "recognition" in joined
    assert "facenet" in joined


def test_fallback_plan_keeps_acronyms_and_anchors_every_query_to_the_domain() -> None:
    # Observed live on a survey of agentic AI with no extracted keywords:
    # the plan cut "AI" (too short) and took the research problem's first
    # words, searching for "agentic systems there striking lack readily
    # available structured literature review" -- which matched generic
    # literature reviews from every field (genomics, surgery, climate).
    profile = _profile(
        title="Agentic AI: A Comprehensive Survey of Technologies, Applications, and Societal Implications",
        keywords=[],
        domain=ProfileField(value="Agentic AI systems"),
        research_problem=ProfileField(
            value=(
                "There is a striking lack of readily available and understandable materials dedicated to "
                "agentic AI, with foundational concepts scattered across reinforcement learning and LLMs."
            )
        ),
        methods=ProfileList(items=[ProfileField(value="Structured literature review")]),
        datasets=ProfileList(items=[]),
    )
    plan = fallback_plan(profile, citation_anchors=[])
    assert plan.keyword_sets
    for group in plan.keyword_sets:
        assert group[0] == "agentic ai systems", group
    for query in plan.expanded_queries:
        assert "agentic ai" in query
        for filler in ("striking", "readily", "there"):
            assert filler not in query.split()


def test_generate_search_plan_without_a_session_uses_fallback() -> None:
    plan, warnings = asyncio.run(generate_search_plan(_profile(), session=None, citation_anchors=[]))
    assert plan.generated_by == "fallback"
    assert "search_plan_fallback_no_llm" in warnings


_VALID_PLAN_JSON = json.dumps(
    {
        "keyword_sets": [["retrieval augmented generation", "hallucination"], ["dense retrieval", "open domain qa"]],
        "expanded_queries": ["RAG for factual question answering", "retrieval augmented LLM knowledge grounding"],
        "perspective_questions": ["Does retrieval reduce hallucination in long-form QA?"],
    }
)


def _session(handler: httpx.MockTransport) -> LlmSession:
    from app.domain.user import LlmProvider

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=handler)),
        api_key="sk-x",
        model="test-model",
        provider=LlmProvider.GROQ,
    )


def test_generate_search_plan_with_llm_parses_a_plan() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": _VALID_PLAN_JSON}}]})

    plan, warnings = asyncio.run(
        generate_search_plan(_profile(), session=_session(httpx.MockTransport(handler)), citation_anchors=["10.1/x"])
    )
    assert plan.generated_by == "llm"
    assert plan.keyword_sets[0] == ["retrieval augmented generation", "hallucination"]
    assert "RAG for factual question answering" in plan.expanded_queries
    assert plan.citation_anchors == ["10.1/x"]
    assert warnings == []


def test_generate_search_plan_with_malformed_llm_output_falls_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    plan, warnings = asyncio.run(
        generate_search_plan(_profile(), session=_session(httpx.MockTransport(handler)), citation_anchors=[])
    )
    assert plan.generated_by == "fallback"
    assert "search_plan_fallback_llm_error" in warnings


def test_generate_search_plan_survives_a_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    plan, warnings = asyncio.run(
        generate_search_plan(_profile(), session=_session(httpx.MockTransport(handler)), citation_anchors=[])
    )
    assert plan.generated_by == "fallback"
    assert warnings  # a fallback warning was recorded, not an exception raised
