"""Workspace summary (Architecture §4 `Synthesis`; API spec §6
`POST /workspaces/{id}/summary`; Roadmap Phase 9).

Same grounding machinery as RAG: the LLM writes sentences tagged with the
`chunk_id`(s) they rest on, each is `IsSupported?`-checked, unsupported
sentences are dropped, and a faithfulness score is attached. Reference
strings are never generated.

`length` ("short"/"medium"/"long") only changes the instruction; long
inputs are handled by the caller passing a capped set of chunks (a real
map-reduce over very large workspaces is a later optimisation).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.citation import ArtefactKind, Claim
from app.domain.rag import AnswerSentence, FilteredChunk
from app.llm.session import LlmSession
from app.services.rag.faithfulness import passes, score_faithfulness
from app.services.rag.generate import generate_answer
from app.services.rag.verify import verify_sentences

_INSTRUCTION = {
    "short": "In 2-3 sentences, summarise the key contributions across these papers.",
    "medium": "In 4-6 sentences, summarise the problems, methods and main findings across these papers.",
    "long": "In 8-12 sentences, give a thorough summary of the problems, methods, datasets, findings and limitations across these papers.",
}


@dataclass
class SummaryResult:
    text: str
    sentences: list[AnswerSentence] = field(default_factory=list)
    faithfulness: float = 0.0
    faithfulness_passed: bool = True
    unsupported_dropped: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_claims(self, *, workspace_id: str, artefact_id: str) -> list[Claim]:
        out: list[Claim] = []
        for i, s in enumerate(self.sentences):
            if not s.chunk_ids:
                continue
            out.append(
                Claim(
                    claim_id=f"clm_{artefact_id}_{i}",
                    workspace_id=workspace_id,
                    artefact_kind=ArtefactKind.SUMMARY.value,
                    artefact_id=artefact_id,
                    sentence=s.text,
                    supporting_chunk_ids=list(s.chunk_ids),
                    is_supported=s.is_supported,
                )
            )
        return out


async def summarize(
    session: LlmSession | None,
    chunks: list[FilteredChunk],
    *,
    length: str,
    faithfulness_min: float,
) -> SummaryResult:
    if session is None or not chunks:
        return SummaryResult(text="", warnings=["summary_unavailable"])

    instruction = _INSTRUCTION.get(length, _INSTRUCTION["medium"])
    draft = await generate_answer(session, instruction, chunks)
    if not draft.ok:
        return SummaryResult(
            text="",
            prompt_tokens=draft.prompt_tokens,
            completion_tokens=draft.completion_tokens,
            warnings=["summary_generation_failed"],
        )

    chunk_text = {c.chunk_id: c.text for c in chunks}
    verified, pt, ct = await verify_sentences(session, draft.sentences, chunk_text)
    kept = [s for s in verified if s.chunk_ids and s.is_supported]
    faith = score_faithfulness(" ".join(s.text for s in kept), list(chunk_text.values()))
    return SummaryResult(
        text=" ".join(s.text for s in kept),
        sentences=kept,
        faithfulness=faith,
        faithfulness_passed=passes(faith, faithfulness_min),
        unsupported_dropped=len(verified) - len(kept),
        prompt_tokens=draft.prompt_tokens + pt,
        completion_tokens=draft.completion_tokens + ct,
        warnings=[] if kept else ["no_supported_sentences"],
    )
