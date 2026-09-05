"""Stage S1-S3 orchestration: the full ingestion pipeline for one PDF.

This is deterministic glue code -- no LLM calls (Architecture §3: S1/S2/S3
are all deterministic/retrieval). It composes the modules in this package
and persists the result via app.db.repository. Called from the async
ingest job (app/jobs/runner.py), which is what the `POST /papers/upload`
endpoint schedules after synchronous S1 validation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.paper import ParseConfidence, ParsedDocument, RawReference, Section, TableBlock
from app.security.pdf_sanitizer import validate_upload
from app.services.ingest.chunker import build_chunks
from app.services.ingest.cleaner import clean_pages
from app.services.ingest.confidence import assess_confidence
from app.services.ingest.pdf_loader import LoadedPage, load_pdf
from app.services.ingest.reference_parser import parse_references
from app.services.ingest.section_splitter import split_sections
from app.services.ingest.table_extractor import extract_table_blocks

_TITLE_HASH_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_MIN_FALLBACK_TITLE_LEN = 8


@dataclass(frozen=True)
class IngestResult:
    paper_id: str
    parse_confidence: ParseConfidence
    sections: list[Section] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    references: list[RawReference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    chunk_count: int = 0
    deduplicated: bool = False


def _title_hash(title: str) -> str:
    normalized = _TITLE_HASH_NORMALIZE_RE.sub(" ", title.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _fallback_title(pages: list[LoadedPage]) -> str | None:
    """Best-effort title when the PDF has no Title metadata: the first
    reasonably long line of page 1. Never guesses authors."""
    for page in pages:
        for line in page.text.splitlines():
            candidate = line.strip()
            if len(candidate) >= _MIN_FALLBACK_TITLE_LEN:
                return candidate
    return None


def run_ingestion(
    db: Session,
    paper_id: str,
    pdf_bytes: bytes,
    filename: str,
    settings: Settings,
) -> IngestResult:
    """Validate, parse, chunk and persist one uploaded PDF.

    Idempotent by content hash: re-uploading the same bytes returns the
    already-stored paper (`deduplicated=True`) instead of creating a
    duplicate row -- see docs/architecture/ResearchNexus_API_Specification.md
    §4 (`POST /papers/upload`).
    """
    meta = validate_upload(pdf_bytes, filename, settings)

    existing = repo.find_paper_by_sha256(db, meta.sha256)
    if existing is not None:
        existing_chunks = repo.get_chunks_for_paper(db, existing.id)
        return IngestResult(
            paper_id=existing.id,
            parse_confidence=ParseConfidence(existing.parse_confidence or ParseConfidence.LOW.value),
            sections=[Section(**s) for s in existing.sections],
            tables=[TableBlock(**t) for t in existing.tables],
            references=[RawReference(**r) for r in existing.references],
            warnings=list(existing.warnings or []),
            chunk_count=len(existing_chunks),
            deduplicated=True,
        )

    pdf_path = settings.pdf_storage_dir() / f"{paper_id}.pdf"
    pdf_path.write_bytes(pdf_bytes)

    raw = load_pdf(pdf_bytes, settings)
    _cleaned_pages, full_text, page_ranges = clean_pages([p.text for p in raw.pages])
    sections = split_sections(full_text, page_ranges)
    tables = extract_table_blocks(raw.pages, _cleaned_pages)
    references = parse_references(full_text, sections)

    has_text_layer = bool(full_text.strip())
    confidence, confidence_warnings = assess_confidence(
        page_count=raw.page_count,
        full_text=full_text,
        sections=sections,
        references=references,
        has_text_layer=has_text_layer,
    )

    title = raw.title or _fallback_title(raw.pages) or filename
    parsed = ParsedDocument(
        full_text=full_text,
        sections=sections,
        tables=tables,
        references=references,
        page_count=raw.page_count,
        has_text_layer=has_text_layer,
        parse_confidence=confidence,
        title=title,
        authors=raw.authors,
        warnings=[*raw.warnings, *confidence_warnings],
    )

    chunks = build_chunks(paper_id, full_text, sections, tables, page_ranges, settings)

    paper_orm = repo.paper_from_ingest(
        paper_id=paper_id,
        meta=meta,
        parsed=parsed,
        pdf_path=str(pdf_path),
        title_hash=_title_hash(title),
    )
    repo.save_paper(db, paper_orm)
    repo.save_chunks(db, chunks)

    return IngestResult(
        paper_id=paper_id,
        parse_confidence=confidence,
        sections=sections,
        tables=tables,
        references=references,
        warnings=parsed.warnings,
        chunk_count=len(chunks),
        deduplicated=False,
    )
