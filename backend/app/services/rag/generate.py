"""Grounded answer generation (Architecture §1.1 "RAG answer generation ...
LLM (structured, per-sentence chunk tags)"; Roadmap Phase 9).

The LLM returns sentences, each tagged with the `chunk_id`(s) it is
grounded in. Two guards run on the way out:
- a `chunk_id` not in the retrieved set is dropped (the LLM cannot cite a
  chunk that was not shown to it);
- `[1]` / `(Author, 2024)` strings are stripped from the prose -- reference
  strings come only from the deterministic formatter.
No session / any failure -> `ok=False` (the pipeline surfaces a warning);
with `raise_provider_errors` a provider failure is raised instead. An empty
`sentences` list is the model saying the context doesn't answer the
question (`ok=True`, no sentences).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field, field_validator

from app.domain.rag import FilteredChunk
from app.llm.session import LlmSession
from app.services.rag._llm import chat_json, strip_fabricated_references

_SYSTEM = (
    "Answer the QUESTION using ONLY the numbered CONTEXT chunks. Write 1-5 "
    "short sentences. Return JSON: {\"sentences\":[{\"text\":\"<one sentence, "
    "no citation markers>\",\"chunk_ids\":[\"<id>\"]}]}. Every sentence MUST "
    "list at least one chunk_id it is grounded in, taken only from the "
    "context. If the context does not answer the question, return "
    '{"sentences":[]}.'
)


class _GenSentence(BaseModel):
    text: str
    chunk_ids: list[str] = Field(default_factory=list)

    @field_validator("chunk_ids", mode="before")
    @classmethod
    def _one_id_is_a_list(cls, v: object) -> object:
        return [v] if isinstance(v, str) else v  # "chk_1" where ["chk_1"] was asked for


class _GenResult(BaseModel):
    sentences: list[_GenSentence] = Field(default_factory=list)


@dataclass
class DraftSentence:
    text: str
    chunk_ids: list[str]


@dataclass
class DraftAnswer:
    ok: bool
    sentences: list[DraftSentence] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


async def generate_answer(
    session: LlmSession | None,
    query: str,
    chunks: list[FilteredChunk],
    *,
    raise_provider_errors: bool = False,
) -> DraftAnswer:
    usable = [c for c in chunks if c.kept]
    if session is None or not usable:
        return DraftAnswer(ok=False)

    valid_ids = {c.chunk_id for c in usable}
    user = f"QUESTION: {query}\n\nCONTEXT:\n" + "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in usable)
    parsed, pt, ct = await chat_json(session, _SYSTEM, user, _GenResult, raise_provider_errors=raise_provider_errors)
    if parsed is None:
        return DraftAnswer(ok=False, prompt_tokens=pt, completion_tokens=ct)
    assert isinstance(parsed, _GenResult)

    out: list[DraftSentence] = []
    for s in parsed.sentences:
        text = strip_fabricated_references(s.text).strip()
        if not text:
            continue
        cited = [cid for cid in s.chunk_ids if cid in valid_ids]  # drop invented ids
        out.append(DraftSentence(text=text, chunk_ids=cited))
    return DraftAnswer(ok=True, sentences=out, prompt_tokens=pt, completion_tokens=ct)
