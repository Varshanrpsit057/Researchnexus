"""Stage S2 (part 4): turn pdfplumber's raw table grids into TableBlocks.

Deterministic. Captions are paired with tables on the same page by order of
appearance -- pdfplumber does not link a table to a specific caption, so
when a page has multiple tables this is a documented heuristic, not a
guarantee (see docs/architecture/ResearchNexus_Implementation_Roadmap.md
Phase 2 acceptance criteria: "table-recall", not "caption-accuracy")."""

from __future__ import annotations

import re

from app.domain.paper import TableBlock
from app.services.ingest.pdf_loader import LoadedPage

_CAPTION_RE = re.compile(r"^Table\s+\d+\b", re.IGNORECASE)


def _find_captions_on_page(page_text: str) -> list[str]:
    return [line.strip() for line in page_text.splitlines() if _CAPTION_RE.match(line.strip())]


def _format_raw_table(rows: list[list[str | None]]) -> str:
    return "\n".join("\t".join(cell if cell else "" for cell in row) for row in rows)


def _is_meaningful(rows: list[list[str | None]]) -> bool:
    return any(cell and cell.strip() for row in rows for cell in row)


def extract_table_blocks(pages: list[LoadedPage], cleaned_page_texts: list[str]) -> list[TableBlock]:
    """`cleaned_page_texts[i]` must correspond to `pages[i]` (same order)."""
    blocks: list[TableBlock] = []
    order = 0
    for page, page_text in zip(pages, cleaned_page_texts, strict=True):
        captions = _find_captions_on_page(page_text)
        table_index = 0
        for raw_table in page.tables:
            if not raw_table or not _is_meaningful(raw_table):
                continue
            caption = captions[table_index] if table_index < len(captions) else None
            blocks.append(
                TableBlock(
                    page=page.number,
                    raw_text=_format_raw_table(raw_table),
                    caption=caption,
                    order=order,
                )
            )
            table_index += 1
            order += 1
    return blocks
