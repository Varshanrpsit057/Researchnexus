"""Multi-paper comparison (Architecture §1.1 "Summarise / key points /
compare ... schema->value tables"; API spec §6 `POST /workspaces/{id}/
compare`; Roadmap Phase 10).

Two stages:
1. `build_schema` -- deterministic. Either the caller's explicit column
   list, or the union of the canonical facets that at least one selected
   paper's `ResearchProfile` has data for. No LLM.
2. `build_comparison` -- per (paper, column) the LLM *proposes* a short
   value and cites a chunk; the value is kept **only if** the cited chunk
   was actually retrieved for that paper and the quote is a verbatim span
   of it. Anything else -> the cell is `null` (missing), never a guess.
   Every kept cell becomes a persisted `Claim`
   (`artefact_kind="comparison_cell"`), and every cell records why it
   looks the way it does (`CellStatus`): found; not stated in the text it
   read; proposed but unsupported; no text to read; or not extracted.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.citation import ArtefactKind, Claim
from app.domain.comparison import (
    CellStatus,
    Comparison,
    ComparisonCell,
    ComparisonRow,
    ComparisonSchema,
    SchemaOrigin,
)
from app.domain.profile import ResearchProfile, SourceSpan
from app.domain.rag import RetrievedChunk
from app.domain.workspace import Grounding, ResearchWorkspace
from app.llm.session import LlmSession
from app.retrieval.workspace_index import WorkspaceChunkIndex
from app.services.rag._llm import chat_json, contains_verbatim
from app.services.rag.retriever import retrieve

DEFAULT_COLUMNS = ["method", "dataset", "metric", "result"]
_MAX_COL_LEN = 40

# canonical facet -> the profile attributes that, if non-empty, make the facet "present"
_CANONICAL: list[tuple[str, tuple[str, ...]]] = [
    ("problem", ("research_problem",)),
    ("method", ("methods", "models", "algorithms")),
    ("dataset", ("datasets",)),
    ("metric", ("evaluation_metrics",)),
    ("result", ("findings",)),
    ("limitation", ("limitations",)),
]


def _norm_column(c: str) -> str:
    return re.sub(r"\s+", " ", c).strip().lower()[:_MAX_COL_LEN]


def _norm_columns(cols: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for c in cols:
        t = _norm_column(c)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _facet_present(profile: ResearchProfile, attrs: tuple[str, ...]) -> bool:
    for attr in attrs:
        value = getattr(profile, attr, None)
        if value is None:
            continue
        if hasattr(value, "items"):  # ProfileList
            if any(i.value.strip() for i in value.items):
                return True
        elif getattr(value, "value", "").strip():  # ProfileField
            return True
    return False


def build_schema(profiles: list[ResearchProfile], *, explicit: list[str] | None) -> ComparisonSchema:
    if explicit is not None:
        cols = _norm_columns(explicit) or list(DEFAULT_COLUMNS)
        return ComparisonSchema(columns=cols, generated_by=SchemaOrigin.DETERMINISTIC_UNION.value)

    present = [facet for facet, attrs in _CANONICAL if any(_facet_present(p, attrs) for p in profiles)]
    return ComparisonSchema(
        columns=present or list(DEFAULT_COLUMNS),
        generated_by=SchemaOrigin.DETERMINISTIC_UNION.value,
    )


# --- per-paper cell extraction ------------------------------------------


class _CellProposal(BaseModel):
    column: str
    value: str | None = None
    chunk_id: str | None = None
    quote: str | None = None
    alternates: list[str] = Field(default_factory=list)


class _PaperCells(BaseModel):
    cells: list[_CellProposal] = Field(default_factory=list)


_SYSTEM = (
    "You compare one PAPER against a list of COLUMNS. For each column, give a "
    "SHORT value (a few words) ONLY if the paper's chunks state it, and copy a "
    "VERBATIM quote from the chunk that supports it plus that chunk's id. If "
    "the paper does not state the column, set value and quote to null. Return "
    'JSON: {"cells":[{"column":"<col>","value":"<short>"|null,"chunk_id":"<id>"'
    '|null,"quote":"<verbatim>"|null,"alternates":["<other verified value>"]}]}. '
    "Never write a value that is not supported by a verbatim quote."
)


# what each field is called in a paper's own words, so each finds its passages
_FIELD_QUERY = {
    "problem": "research problem motivation objective challenge this paper addresses",
    "method": "proposed method approach model architecture technique algorithm",
    "dataset": "dataset data corpus benchmark collected samples participants",
    "metric": "evaluation metric measure accuracy precision recall F1 score",
    "result": "results findings performance achieved improvement outperforms",
    "limitation": "limitations future work drawbacks shortcomings remaining challenges",
}
_MAX_PASSAGES = 12


def _passages_for(db: Session, index: WorkspaceChunkIndex, paper_id: str, columns: list[str], k: int) -> list[RetrievedChunk]:
    """A paper's passages for a comparison: the best few for each field, each
    field searched in its own words within this paper only. One query of all
    the field names together found the passages most like a list of headings
    (remediation, 2026-10-02) -- a full text's method and results sections
    were often missed."""
    per_field = max(2, -(-k // max(len(columns), 1)))
    seen: set[str] = set()
    out: list[RetrievedChunk] = []
    for column in columns:
        for chunk in retrieve(db, index, _FIELD_QUERY.get(column, column), k=per_field, scope_paper_ids=[paper_id]):
            if chunk.chunk_id not in seen:
                seen.add(chunk.chunk_id)
                out.append(chunk)
    return out[: max(k, min(_MAX_PASSAGES, per_field * len(columns)))]


@dataclass
class ComparisonResult:
    comparison: Comparison
    claims: list[Claim] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _empty_row(paper_id: str, columns: list[str], grounding: str, status: CellStatus) -> ComparisonRow:
    return ComparisonRow(
        paper_id=paper_id,
        cells={c: ComparisonCell(column=c, grounding=grounding, status=status) for c in columns},
    )


def _grounded_cell(proposal: _CellProposal, column: str, by_id: dict, grounding: str) -> ComparisonCell | None:
    """Deterministic evidence validation -- runs before anything is persisted."""
    if not proposal.value or not proposal.value.strip():
        return None
    if not proposal.chunk_id or proposal.chunk_id not in by_id:
        return None  # cited a chunk that was not retrieved for this paper
    src = by_id[proposal.chunk_id]
    if not proposal.quote or not contains_verbatim(src.text, proposal.quote):
        return None  # quote is not a verbatim span -> reject
    alternates = [a.strip() for a in proposal.alternates if a.strip() and contains_verbatim(src.text, a)]
    return ComparisonCell(
        column=column,
        text=proposal.value.strip(),
        span=SourceSpan(
            paper_id=src.paper_id, section=src.section, page=src.page, quote=proposal.quote.strip()[:400]
        ),
        grounding=grounding,
        conflicting=alternates,
    )


async def _none() -> None:
    return None


async def build_comparison(
    db: Session,
    *,
    workspace: ResearchWorkspace,
    comparison_id: str,
    paper_ids: list[str],
    column_schema: ComparisonSchema,
    session: LlmSession | None,
    settings: Settings,
    index: WorkspaceChunkIndex,
) -> ComparisonResult:
    columns = list(column_schema.columns)
    grounding_by_paper = {
        p.paper_id: (Grounding.ABSTRACT.value if p.grounding is Grounding.ABSTRACT else Grounding.FULL_TEXT.value)
        for p in workspace.papers
    }
    result = ComparisonResult(
        comparison=Comparison(
            comparison_id=comparison_id,
            workspace_id=workspace.workspace_id,
            column_schema=column_schema,
            paper_ids=list(paper_ids),
        )
    )
    total_cells = len(paper_ids) * len(columns)
    grounded = 0

    if session is None:
        result.warnings.append("comparison_unavailable_no_session")

    # each paper's passages first; then every paper is read at once (bounded),
    # and the rows are assembled in the papers' order -- the same result as
    # reading them one after another (remediation, 2026-10-02: 4 papers took 60 s)
    passages = [_passages_for(db, index, pid, columns, settings.compare_retrieve_k) for pid in paper_ids]
    gate = asyncio.Semaphore(max(1, settings.compare_llm_concurrency))

    async def read(pid: str, retrieved: list[RetrievedChunk]) -> tuple[_PaperCells | None, int, int]:
        user = (
            f"PAPER: {pid}\nCOLUMNS: {', '.join(columns)}\n\nCHUNKS:\n"
            + "\n\n".join(f"[{c.chunk_id}] {c.text}" for c in retrieved)
        )
        async with gate:
            parsed, pt, ct = await chat_json(session, _SYSTEM, user, _PaperCells)
        return (parsed if isinstance(parsed, _PaperCells) else None), pt, ct

    readings: list[tuple[_PaperCells | None, int, int] | None] = list(
        await asyncio.gather(
            *(
                read(pid, retrieved) if session is not None and retrieved else _none()
                for pid, retrieved in zip(paper_ids, passages, strict=True)
            )
        )
    )

    for p_idx, (pid, retrieved, reading) in enumerate(zip(paper_ids, passages, readings, strict=True)):
        grounding = grounding_by_paper.get(pid, Grounding.FULL_TEXT.value)
        # until the paper is read, nothing about it is concluded
        row = _empty_row(pid, columns, grounding, CellStatus.NOT_EXTRACTED if retrieved else CellStatus.NO_TEXT)
        if not retrieved:
            result.warnings.append(f"no_text:{pid}")

        if reading is not None:
            parsed, pt, ct = reading
            by_id = {c.chunk_id: c for c in retrieved}
            result.prompt_tokens += pt
            result.completion_tokens += ct
            if parsed is None:
                result.warnings.append(f"cell_extraction_failed:{pid}")
            else:
                # the text was read: a column it returns nothing for is not stated
                for unread in row.cells.values():
                    unread.status = CellStatus.NOT_STATED
                for proposal in parsed.cells:
                    col = _norm_column(proposal.column)
                    if col not in row.cells:
                        continue  # LLM cannot introduce a column
                    cell = _grounded_cell(proposal, col, by_id, grounding)
                    if cell is None:
                        if proposal.value and proposal.value.strip():
                            row.cells[col].status = CellStatus.UNSUPPORTED  # proposed, not verifiable: never shown
                        continue
                    claim_id = f"clm_{comparison_id}_{p_idx}_{col}"
                    cell.claim_id = claim_id
                    row.cells[col] = cell
                    grounded += 1
                    result.claims.append(
                        Claim(
                            claim_id=claim_id,
                            workspace_id=workspace.workspace_id,
                            artefact_kind=ArtefactKind.COMPARISON_CELL.value,
                            artefact_id=comparison_id,
                            sentence=f"{col}: {cell.text}",
                            supporting_chunk_ids=[str(proposal.chunk_id)],
                            supporting_paper_ids=[pid],
                            is_supported=True,
                        )
                    )

        result.comparison.rows.append(row)

    result.comparison.coverage = round(grounded / total_cells, 6) if total_cells else 0.0
    return result
