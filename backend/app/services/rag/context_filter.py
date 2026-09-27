"""LLM contextual chunk filter (Architecture §1.1 "RAG contextual chunk
filter ... keep only relevant sentences"; Roadmap Phase 9).

The LLM may only *narrow* a chunk to sentences it copied verbatim, or drop
it. A returned `relevant_text` that is not a literal span of its source
chunk is ignored (the whole chunk is kept instead) -- the filter can never
introduce text. No session / any failure -> every chunk kept whole, except
that with `raise_provider_errors` a provider failure is raised (chat: the
same provider writes the answer next, so the question fails with the reason).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.rag import FilteredChunk, RetrievedChunk
from app.llm.session import LlmSession
from app.services.rag._llm import chat_json, contains_verbatim

_SYSTEM = (
    "You are given a QUESTION and numbered CONTEXT chunks. For each chunk that "
    "contains information useful for answering the question, copy VERBATIM only "
    "the relevant sentence(s) from that chunk. Drop chunks with nothing "
    'relevant by omitting them. Return JSON: {"chunks":[{"chunk_id":"<id>",'
    '"relevant_text":"<verbatim sentences>"}]}. Never write text that is not '
    "present in the chunk."
)


class _FilteredChunk(BaseModel):
    chunk_id: str
    relevant_text: str = ""


class _FilterResult(BaseModel):
    chunks: list[_FilteredChunk] = Field(default_factory=list)


def _keep_whole(chunks: list[RetrievedChunk]) -> list[FilteredChunk]:
    return [
        FilteredChunk(
            chunk_id=c.chunk_id, paper_id=c.paper_id, text=c.text, section=c.section, page=c.page, kept=True
        )
        for c in chunks
    ]


async def filter_chunks(
    session: LlmSession | None, query: str, chunks: list[RetrievedChunk], *, raise_provider_errors: bool = False
) -> tuple[list[FilteredChunk], int, int]:
    if session is None or not chunks:
        return _keep_whole(chunks), 0, 0

    by_id = {c.chunk_id: c for c in chunks}
    user = f"QUESTION: {query}\n\nCONTEXT:\n" + "\n\n".join(
        f"[{c.chunk_id}] {c.text}" for c in chunks
    )
    parsed, pt, ct = await chat_json(session, _SYSTEM, user, _FilterResult, raise_provider_errors=raise_provider_errors)
    if parsed is None:
        return _keep_whole(chunks), pt, ct
    assert isinstance(parsed, _FilterResult)

    kept: dict[str, FilteredChunk] = {}
    for item in parsed.chunks:
        src = by_id.get(item.chunk_id)
        if src is None:
            continue  # LLM cannot introduce a chunk id
        text = item.relevant_text.strip()
        if not text or not contains_verbatim(src.text, text):
            text = src.text  # paraphrase / empty -> fall back to the whole chunk
        kept[src.chunk_id] = FilteredChunk(
            chunk_id=src.chunk_id, paper_id=src.paper_id, text=text, section=src.section, page=src.page, kept=True
        )

    out: list[FilteredChunk] = []
    for c in chunks:
        out.append(
            kept.get(
                c.chunk_id,
                FilteredChunk(
                    chunk_id=c.chunk_id, paper_id=c.paper_id, text=c.text, section=c.section, page=c.page, kept=False
                ),
            )
        )
    return out, pt, ct
