from __future__ import annotations

import asyncio

import httpx

from app.domain.ranking import SIGNAL_NAMES, RankingExplanation, SignalScores
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.ranking.explain import add_llm_prose, build_explanation


def test_every_bullet_maps_to_a_signal_above_the_threshold() -> None:
    signals = SignalScores(semantic_doc=0.82, problem_sim=0.71, method_sim=0.30, citation=0.6)
    expl = build_explanation(signals, threshold=0.5)

    assert expl.template_only is True
    assert set(expl.signals_used) == {"semantic_doc", "problem_sim", "citation"}
    assert len(expl.bullet_reasons) == len(expl.signals_used)
    # a below-threshold signal must NOT produce a bullet
    assert not any("method" in b.lower() for b in expl.bullet_reasons)
    # every bullet names a used signal and shows its actual value
    assert any("0.82" in b for b in expl.bullet_reasons)
    for used in expl.signals_used:
        assert used in SIGNAL_NAMES


def test_bullets_are_ordered_by_signal_strength() -> None:
    expl = build_explanation(SignalScores(problem_sim=0.6, semantic_doc=0.9, citation=0.7), threshold=0.5)
    assert "0.90" in expl.bullet_reasons[0]  # strongest first


def test_never_empty_when_all_signals_are_below_threshold() -> None:
    expl = build_explanation(SignalScores(semantic_doc=0.2, recency=0.1), threshold=0.5)
    assert expl.bullet_reasons  # still one fallback bullet naming the strongest
    assert expl.signals_used == ["semantic_doc"]
    assert "0.20" in expl.bullet_reasons[0]


def test_no_bullet_without_a_signal() -> None:
    expl = build_explanation(SignalScores(), threshold=0.5)
    assert expl.signals_used == []
    assert expl.bullet_reasons == []
    assert expl.prose  # prose still non-empty


def _session(handler: httpx.MockTransport) -> LlmSession:
    from app.domain.user import LlmProvider

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=handler)),
        api_key="sk-x",
        model="m",
        provider=LlmProvider.GROQ,
    )


def _base() -> RankingExplanation:
    return build_explanation(SignalScores(semantic_doc=0.8, problem_sim=0.7), threshold=0.5)


def test_llm_prose_rephrases_without_touching_the_bullets() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "This paper is a strong document-level match that tackles a closely related problem."}}]})

    base = _base()
    out = asyncio.run(add_llm_prose(base, session=_session(httpx.MockTransport(handler))))
    assert out.bullet_reasons == base.bullet_reasons  # bullets are never LLM-authored
    assert out.template_only is False
    assert out.prose != base.prose


def test_llm_failure_falls_back_to_the_template_prose() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    base = _base()
    out = asyncio.run(add_llm_prose(base, session=_session(httpx.MockTransport(handler))))
    assert out == base  # unchanged, still template_only
    assert out.template_only is True
