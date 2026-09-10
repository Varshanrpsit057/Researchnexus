"""`IsSupported?` verification (Architecture §1.1 "RAG IsSupported?
verification ... Self-RAG-style; drop/flag unsupported"; Roadmap Phase 9).

For each drafted sentence, the LLM judges whether its cited chunks fully
support it. Safe defaults:
- a sentence with no cited chunk is unsupported without an LLM call;
- an LLM failure leaves every checked sentence unsupported (Architecture
  §4 EvidenceVerifier: "timeout -> treat as unsupported").
The caller decides whether unsupported sentences are dropped from the prose
or kept with a flag.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.rag import AnswerSentence
from app.llm.session import LlmSession
from app.services.rag._llm import chat_json
from app.services.rag.generate import DraftSentence

_SYSTEM = (
    "For each numbered STATEMENT and its EVIDENCE, decide whether the evidence "
    "fully supports the statement (no unsupported detail). Return JSON: "
    '{"results":[{"index":<int>,"supported":<bool>}]}.'
)


class _VerifyItem(BaseModel):
    index: int
    supported: bool = False


class _VerifyResult(BaseModel):
    results: list[_VerifyItem] = Field(default_factory=list)


async def verify_sentences(
    session: LlmSession | None,
    drafted: list[DraftSentence],
    chunk_text_by_id: dict[str, str],
) -> tuple[list[AnswerSentence], int, int]:
    checkable = [(i, s) for i, s in enumerate(drafted) if s.chunk_ids]
    supported: set[int] = set()
    pt = ct = 0

    if session is not None and checkable:
        blocks = []
        for i, s in checkable:
            evidence = "\n".join(f"- {chunk_text_by_id.get(cid, '')}" for cid in s.chunk_ids)
            blocks.append(f"[{i}] STATEMENT: {s.text}\nEVIDENCE:\n{evidence}")
        parsed, pt, ct = await chat_json(session, _SYSTEM, "\n\n".join(blocks), _VerifyResult)
        if parsed is not None:
            assert isinstance(parsed, _VerifyResult)
            supported = {r.index for r in parsed.results if r.supported}

    out: list[AnswerSentence] = []
    for i, s in enumerate(drafted):
        is_sup = i in supported
        out.append(
            AnswerSentence(
                text=s.text,
                chunk_ids=list(s.chunk_ids),
                is_supported=is_sup,
                flagged_unsupported=not is_sup,
            )
        )
    return out, pt, ct
