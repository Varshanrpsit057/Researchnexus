"""Abstract-only papers in the workspace index.

A paper found by discovery has no PDF -- only its title and abstract -- and
joins a workspace with `grounding="abstract"`. But the workspace index,
chat retrieval and comparison all read `paper_chunks`, and only an
uploaded PDF was ever chunked: an abstract-only paper was invisible to all
three (a comparison row of nothing but empty cells, a chat that could never
cite it). Its abstract is its text, so it becomes a single chunk, section
"Abstract", kind ABSTRACT -- the same shape an uploaded paper's abstract
section gets from the chunker.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db import repository as repo
from app.domain.chunk import ChunkKind, PaperChunk


def abstract_chunk_id(paper_id: str) -> str:
    return f"chk_{paper_id}_abstract"


def ensure_abstract_chunks(db: Session, paper_ids: list[str]) -> int:
    """Chunk the abstract of every abstract-only paper that has no chunks
    yet. Idempotent; papers with full text are left to the PDF chunker.
    Returns how many chunks were added."""
    added: list[PaperChunk] = []
    for pid in dict.fromkeys(paper_ids):
        paper = repo.get_paper(db, pid)
        if paper is None or paper.has_full_text:
            continue
        text = (paper.abstract or "").strip()
        if not text or repo.get_chunks_for_paper(db, pid):
            continue
        added.append(
            PaperChunk(
                chunk_id=abstract_chunk_id(pid),
                paper_id=pid,
                section="Abstract",
                section_order=0,
                char_start=0,
                char_end=len(text),
                kind=ChunkKind.ABSTRACT,
                text=text,
                token_count=len(text.split()),
            )
        )
    repo.save_chunks(db, added)
    return len(added)
