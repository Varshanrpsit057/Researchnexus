from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.citation import Claim
from app.domain.rag import FilteredChunk, RetrievedChunk
from app.domain.user import LlmProvider
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.retrieval.reranker import FakeCrossEncoder
from app.services.citations.validate import link_claims, strip_fabricated_references
from app.services.rag.answerability import assess
from app.services.rag.context_filter import filter_chunks
from app.services.rag.faithfulness import passes, score_faithfulness
from app.services.rag.generate import DraftSentence, generate_answer
from app.services.rag.rerank import rerank
from app.services.rag.verify import verify_sentences


def _session(payload: object | str, status: int = 200) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="err")
        content = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x",
        model="m",
        provider=LlmProvider.GROQ,
    )


def _rc(cid: str, pid: str, text: str, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(chunk_id=cid, paper_id=pid, text=text, section="Methods", page=3, score=score)


def _fc(cid: str, pid: str, text: str, kept: bool = True) -> FilteredChunk:
    return FilteredChunk(chunk_id=cid, paper_id=pid, text=text, kept=kept)


# --- rerank -----------------------------------------------------------------


def test_rerank_reorders_by_cross_encoder_and_truncates() -> None:
    chunks = [
        _rc("c1", "p1", "unrelated text about gardening"),
        _rc("c2", "p1", "dense passage retrieval for question answering"),
        _rc("c3", "p2", "retrieval question answering benchmark"),
    ]
    out = rerank("retrieval question answering", chunks, FakeCrossEncoder(), top_n=2)
    assert [c.chunk_id for c in out] == ["c3", "c2"]
    s0, s1 = out[0].rerank_score, out[1].rerank_score
    assert s0 is not None and s1 is not None and s0 >= s1


# --- contextual filter ----------------------------------------------------


def test_context_filter_keeps_only_verbatim_sentences_and_drops_unmentioned() -> None:
    chunks = [
        _rc("c1", "p1", "We use dense retrieval. We also bake bread on weekends."),
        _rc("c2", "p2", "This chunk is entirely off topic."),
    ]
    payload = {"chunks": [{"chunk_id": "c1", "relevant_text": "We use dense retrieval."}]}
    out, pt, ct = asyncio.run(filter_chunks(_session(payload), "how is retrieval done?", chunks))
    by_id = {c.chunk_id: c for c in out}
    assert by_id["c1"].kept is True and by_id["c1"].text == "We use dense retrieval."
    assert by_id["c2"].kept is False  # omitted by the filter -> dropped


def test_context_filter_falls_back_to_whole_chunk_on_paraphrase() -> None:
    chunks = [_rc("c1", "p1", "We use dense retrieval with hard negatives.")]
    payload = {"chunks": [{"chunk_id": "c1", "relevant_text": "the authors used retrieval"}]}  # not verbatim
    out, _, _ = asyncio.run(filter_chunks(_session(payload), "q", chunks))
    assert out[0].kept is True and out[0].text == "We use dense retrieval with hard negatives."


def test_context_filter_degrades_to_keep_all_without_a_session() -> None:
    chunks = [_rc("c1", "p1", "text one"), _rc("c2", "p2", "text two")]
    out, pt, ct = asyncio.run(filter_chunks(None, "q", chunks))
    assert [c.kept for c in out] == [True, True] and (pt, ct) == (0, 0)


def test_context_filter_degrades_on_provider_error() -> None:
    chunks = [_rc("c1", "p1", "text one")]
    out, _, _ = asyncio.run(filter_chunks(_session("x", status=503), "q", chunks))
    assert out[0].kept is True and out[0].text == "text one"


# --- generation ---------------------------------------------------------


def test_generate_drops_invented_chunk_ids_and_strips_reference_markers() -> None:
    chunks = [_fc("c1", "p1", "Dense retrieval improves recall."), _fc("c2", "p2", "Rerankers add precision.")]
    payload = {
        "sentences": [
            {"text": "Dense retrieval improves recall [1].", "chunk_ids": ["c1", "c_invented"]},
            {"text": "Rerankers add precision (Smith et al., 2021).", "chunk_ids": ["c2"]},
        ]
    }
    draft = asyncio.run(generate_answer(_session(payload), "q", chunks))
    assert draft.ok is True
    assert draft.sentences[0].text == "Dense retrieval improves recall."
    assert draft.sentences[0].chunk_ids == ["c1"]  # invented id removed
    assert draft.sentences[1].text == "Rerankers add precision."


def test_generate_returns_not_ok_without_a_session_or_on_failure() -> None:
    chunks = [_fc("c1", "p1", "text")]
    assert asyncio.run(generate_answer(None, "q", chunks)).ok is False
    assert asyncio.run(generate_answer(_session("not json"), "q", chunks)).ok is False


# --- verification -----------------------------------------------------


def test_verify_marks_supported_and_flags_unsupported() -> None:
    drafted = [
        DraftSentence(text="A is true.", chunk_ids=["c1"]),
        DraftSentence(text="B is unsupported.", chunk_ids=["c2"]),
        DraftSentence(text="C has no chunk.", chunk_ids=[]),
    ]
    payload = {"results": [{"index": 0, "supported": True}, {"index": 1, "supported": False}]}
    out, pt, ct = asyncio.run(verify_sentences(_session(payload), drafted, {"c1": "evidence a", "c2": "evidence b"}))
    assert out[0].is_supported is True and out[0].flagged_unsupported is False
    assert out[1].is_supported is False and out[1].flagged_unsupported is True
    assert out[2].is_supported is False  # no chunk -> unsupported without an LLM call


def test_verify_treats_llm_failure_as_unsupported() -> None:
    drafted = [DraftSentence(text="A.", chunk_ids=["c1"])]
    out, _, _ = asyncio.run(verify_sentences(_session("x", status=500), drafted, {"c1": "e"}))
    assert out[0].is_supported is False and out[0].flagged_unsupported is True


# --- faithfulness ---------------------------------------------------


def test_faithfulness_is_context_token_recall() -> None:
    ctx = ["dense retrieval improves recall on question answering benchmarks"]
    assert score_faithfulness("dense retrieval improves recall", ctx) == 1.0
    assert score_faithfulness("dense retrieval invented quantum teleportation", ctx) < 0.75
    assert passes(0.7, 0.6) and not passes(0.4, 0.6)


# --- answerability ------------------------------------------------


def test_answerability_needs_min_kept_chunks_else_suggests() -> None:
    kept2 = [_fc("c1", "p1", "a"), _fc("c2", "p2", "b")]
    assert assess("q", kept2, min_chunks=2).answerable is True

    thin = [_fc("c1", "p1", "a"), _fc("c2", "p2", "b", kept=False)]
    verdict = assess("What datasets does retrieval augmented generation use?", thin, min_chunks=2)
    assert verdict.answerable is False
    assert verdict.suggestion is not None
    assert "retrieval" in verdict.suggestion and verdict.suggestion.startswith("Not enough in this workspace")


# --- citation validate ------------------------------------------


def test_strip_fabricated_references() -> None:
    assert strip_fabricated_references("Recall improves [3].") == "Recall improves."
    assert strip_fabricated_references("As shown (Lewis et al., 2020) this works.") == "As shown this works."
    assert strip_fabricated_references("Ranges too [1-3] and lists [1, 2].") == "Ranges too and lists."


def test_link_claims_drops_claims_citing_unretrieved_chunks_and_fills_papers() -> None:
    claims = [
        Claim(claim_id="k1", workspace_id="w", artefact_kind="answer", artefact_id="m1", sentence="A.", supporting_chunk_ids=["c1", "c_ghost"]),
        Claim(claim_id="k2", workspace_id="w", artefact_kind="answer", artefact_id="m1", sentence="B.", supporting_chunk_ids=["c_ghost"]),
    ]
    linked = link_claims(claims, retrieved_chunk_ids={"c1", "c2"}, chunk_to_paper={"c1": "p1", "c2": "p2"})
    assert len(linked) == 1
    assert linked[0].claim_id == "k1"
    assert linked[0].supporting_chunk_ids == ["c1"]  # ghost dropped
    assert linked[0].supporting_paper_ids == ["p1"]
