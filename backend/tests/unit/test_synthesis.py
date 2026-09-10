from __future__ import annotations

import asyncio
import json

import httpx

from app.domain.chunk import ChunkKind, PaperChunk
from app.domain.rag import FilteredChunk
from app.domain.user import LlmProvider
from app.llm.providers.openai_compat import OpenAiCompatClient
from app.llm.session import LlmSession
from app.services.synthesis.keypoints import extract_keypoints
from app.services.synthesis.summary import summarize


def _session(payloads: dict[str, object]) -> LlmSession:
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        for needle, payload in payloads.items():
            if needle in body:
                content = payload if isinstance(payload, str) else json.dumps(payload)
                return httpx.Response(200, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 7, "completion_tokens": 4}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    return LlmSession(
        client=OpenAiCompatClient(LlmProvider.GROQ, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))),
        api_key="sk-x", model="m", provider=LlmProvider.GROQ,
    )


def _fc(cid: str, pid: str, text: str) -> FilteredChunk:
    return FilteredChunk(chunk_id=cid, paper_id=pid, text=text, section="Intro", page=1, kept=True)


def _chunk(cid: str, pid: str, text: str) -> PaperChunk:
    return PaperChunk(chunk_id=cid, paper_id=pid, section="Results", page=4, char_start=0, char_end=len(text), kind=ChunkKind.BODY, text=text, token_count=len(text.split()))


# --- summary --------------------------------------------------------------


def test_summary_keeps_only_supported_sentences_and_scores_faithfulness() -> None:
    chunks = [
        _fc("c1", "p1", "Dense retrieval improves recall on question answering."),
        _fc("c2", "p2", "Reranking with cross encoders improves precision."),
    ]
    payloads = {
        "ONLY the numbered CONTEXT": {
            "sentences": [
                {"text": "Dense retrieval improves recall.", "chunk_ids": ["c1"]},
                {"text": "Unrelated speculative claim about fusion reactors.", "chunk_ids": ["c2"]},
            ]
        },
        "fully supports the statement": {"results": [{"index": 0, "supported": True}, {"index": 1, "supported": False}]},
    }
    res = asyncio.run(summarize(_session(payloads), chunks, length="short", faithfulness_min=0.6))
    assert res.text == "Dense retrieval improves recall."
    assert res.unsupported_dropped == 1
    assert res.faithfulness > 0.6 and res.faithfulness_passed is True
    claims = res.to_claims(workspace_id="ws_1", artefact_id="sum_1")
    assert len(claims) == 1 and claims[0].artefact_kind == "summary" and claims[0].supporting_chunk_ids == ["c1"]


def test_summary_unavailable_without_a_session() -> None:
    res = asyncio.run(summarize(None, [_fc("c1", "p1", "x")], length="short", faithfulness_min=0.6))
    assert res.text == "" and "summary_unavailable" in res.warnings


def test_summary_generation_failure_is_a_warning_not_an_error() -> None:
    res = asyncio.run(
        summarize(_session({"ONLY the numbered CONTEXT": "not json"}), [_fc("c1", "p1", "x"), _fc("c2", "p2", "y")], length="medium", faithfulness_min=0.6)
    )
    assert res.text == "" and "summary_generation_failed" in res.warnings


# --- keypoints -----------------------------------------------------


def test_keypoints_drops_paraphrased_or_unknown_chunk_points() -> None:
    chunks = [
        _chunk("c1", "p1", "We introduce a dense retriever trained with in-batch negatives."),
        _chunk("c2", "p1", "On Natural Questions the model reaches 65.2 exact match."),
    ]
    payload = {
        "points": [
            {"facet": "method", "text": "We introduce a dense retriever trained with in-batch negatives.", "chunk_id": "c1"},
            {"facet": "result", "text": "the model reaches sixty five exact match", "chunk_id": "c2"},  # paraphrase -> dropped
            {"facet": "dataset", "text": "trained on ImageNet", "chunk_id": "c_ghost"},  # unknown chunk -> dropped
        ]
    }
    res = asyncio.run(extract_keypoints(_session({"pick a facet": payload, "Extract 3-6 key points": payload}), "p1", chunks))
    assert len(res.points) == 1
    kp = res.points[0]
    assert kp.facet == "method"
    assert kp.span.paper_id == "p1" and kp.span.page == 4
    assert kp.text in chunks[0].text


def test_keypoints_unavailable_without_a_session() -> None:
    res = asyncio.run(extract_keypoints(None, "p1", [_chunk("c1", "p1", "x")]))
    assert res.points == [] and "keypoints_unavailable" in res.warnings
