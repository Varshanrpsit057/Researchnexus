"""Per-paper key points (API spec §6 `POST /workspaces/{id}/keypoints`;
FacetSum-typed points; Roadmap Phase 9).

The LLM proposes points; grounding is deterministic: a point survives only
if its `text` is a **verbatim span** of the chunk it cites (which must be a
real `paper_chunks` row for that paper). Anything paraphrased or citing an
unknown chunk is dropped -- the LLM cannot invent a span.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.domain.chunk import PaperChunk
from app.domain.profile import SourceSpan
from app.llm.session import LlmSession
from app.services.rag._llm import chat_json, contains_verbatim

_FACETS = {"contribution", "method", "dataset", "metric", "result", "limitation"}

_SYSTEM = (
    "Extract 3-6 key points from the PAPER CHUNKS. For each point pick a facet "
    "from [contribution, method, dataset, metric, result, limitation] and copy "
    "a VERBATIM sentence from one chunk as its text. Return JSON: "
    '{"points":[{"facet":"<facet>","text":"<verbatim sentence>","chunk_id":"<id>"}]}. '
    "Never write a sentence that is not present in a chunk."
)


class _Point(BaseModel):
    facet: str
    text: str
    chunk_id: str


class _Points(BaseModel):
    points: list[_Point] = Field(default_factory=list)


@dataclass
class KeyPoint:
    facet: str
    text: str
    span: SourceSpan


@dataclass
class PaperKeyPoints:
    paper_id: str
    points: list[KeyPoint] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    warnings: list[str] = field(default_factory=list)


async def extract_keypoints(
    session: LlmSession | None, paper_id: str, chunks: list[PaperChunk]
) -> PaperKeyPoints:
    if session is None or not chunks:
        return PaperKeyPoints(paper_id=paper_id, warnings=["keypoints_unavailable"])

    by_id = {c.chunk_id: c for c in chunks}
    user = "PAPER CHUNKS:\n" + "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in chunks)
    parsed, pt, ct = await chat_json(session, _SYSTEM, user, _Points)
    if parsed is None:
        return PaperKeyPoints(paper_id=paper_id, prompt_tokens=pt, completion_tokens=ct, warnings=["keypoints_generation_failed"])
    assert isinstance(parsed, _Points)

    points: list[KeyPoint] = []
    for p in parsed.points:
        chunk = by_id.get(p.chunk_id)
        facet = p.facet if p.facet in _FACETS else "contribution"
        if chunk is None or not contains_verbatim(chunk.text, p.text):
            continue  # invented span -> dropped
        points.append(
            KeyPoint(
                facet=facet,
                text=p.text.strip(),
                span=SourceSpan(
                    paper_id=paper_id,
                    section=chunk.section,
                    page=chunk.page,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    quote=p.text.strip()[:400],
                ),
            )
        )
    return PaperKeyPoints(paper_id=paper_id, points=points, prompt_tokens=pt, completion_tokens=ct)
