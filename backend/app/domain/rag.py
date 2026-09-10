"""RAG pipeline value objects (Roadmap Phase 9; Architecture §3 S13 RAG row).

The pipeline stage order is fixed (Architecture §3): retrieve -> rerank ->
contextual filter -> answerability -> generate (per-sentence chunk tags) ->
`IsSupported?` -> faithfulness gate (regenerate once, then warn). Each
object below is the hand-off between two stages.

Grounding rule: a rendered `AnswerSentence` either carries >=1 `chunk_id`
that resolves to a real retrieved `PaperChunk`, or it is `flagged_unsupported`
(kept in the prose, marked) / dropped. It never carries a chunk id the
retriever did not return.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.citation import ArtefactKind, Claim


class RetrievedChunk(BaseModel):
    chunk_id: str
    paper_id: str
    text: str
    section: str | None = None
    page: int | None = None
    score: float = 0.0  # vector similarity
    rerank_score: float | None = None

    @property
    def quote(self) -> str:
        return self.text.strip()


class FilteredChunk(BaseModel):
    """A retrieved chunk after the LLM contextual filter -- `text` may be a
    sentence-level subset of the original chunk; `kept=False` means the
    filter judged it irrelevant and it is excluded from the prompt."""

    chunk_id: str
    paper_id: str
    text: str
    section: str | None = None
    page: int | None = None
    kept: bool = True


class AnswerSentence(BaseModel):
    text: str
    chunk_ids: list[str] = Field(default_factory=list)
    is_supported: bool = False
    flagged_unsupported: bool = False


class RagAnswer(BaseModel):
    answerable: bool
    text: str = ""
    sentences: list[AnswerSentence] = Field(default_factory=list)
    suggestion: str | None = None
    faithfulness: float | None = None
    faithfulness_passed: bool = True
    regenerated: bool = False
    unsupported_dropped: int = 0
    used_chunk_ids: list[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    warnings: list[str] = Field(default_factory=list)

    def to_claims(self, *, workspace_id: str, artefact_id: str, id_prefix: str = "clm") -> list[Claim]:
        """One `Claim` per grounded sentence. Sentences with no chunk id are
        skipped here (they are already flagged/dropped in `sentences`) so
        the Data Model invariant `supporting_chunk_ids != []` always holds."""
        claims: list[Claim] = []
        for i, s in enumerate(self.sentences):
            if not s.chunk_ids:
                continue
            claims.append(
                Claim(
                    claim_id=f"{id_prefix}_{artefact_id}_{i}",
                    workspace_id=workspace_id,
                    artefact_kind=ArtefactKind.ANSWER.value,
                    artefact_id=artefact_id,
                    sentence=s.text,
                    supporting_chunk_ids=list(s.chunk_ids),
                    supporting_paper_ids=[],  # filled by the caller (has the chunk->paper map)
                    is_supported=s.is_supported,
                )
            )
        return claims
