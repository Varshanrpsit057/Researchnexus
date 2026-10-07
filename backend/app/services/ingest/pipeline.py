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
from app.domain.chunk import PaperChunk
from app.domain.paper import ParseConfidence, ParsedDocument, RawReference, Section, TableBlock
from app.security.pdf_sanitizer import PdfFileMeta, validate_upload
from app.services.ingest.chunker import build_chunks
from app.services.ingest.cleaner import clean_pages
from app.services.ingest.confidence import assess_confidence
from app.services.ingest.identifiers import find_doi
from app.services.ingest.pdf_loader import LoadedPage, load_pdf
from app.services.ingest.reference_parser import parse_references
from app.services.ingest.section_splitter import split_sections
from app.services.ingest.table_extractor import extract_table_blocks
from app.services.normalize.text import clean_abstract

_TITLE_HASH_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_MIN_FALLBACK_TITLE_LEN = 8

# Major publishers (Elsevier/ScienceDirect, Springer, IEEE, ...) stamp a
# running header -- "Available online at www.sciencedirect.com", the
# journal/volume/page citation, a bare brand name -- on page 1 ahead of the
# real title; a naive "first long-enough line" picks that stamp instead
# (observed live, against a real ScienceDirect PDF). Conference proceedings
# additionally print the event name ("International Conference on ...")
# directly above the paper's own title -- a phrasing no paper title itself
# uses. None of these patterns are plausible substrings of a real title.
_FALLBACK_TITLE_SKIP_RE = re.compile(
    r"available\s+online|contents\s+lists\s+available|sciencedirect|"
    r"www\.|https?://|\belsevier\b|\bspringer\b|ieee\s*xplore|"
    r"\bconference\s+on\b|\bworkshop\s+on\b|\bsymposium\s+on\b|"
    r"\d+\s*\(\d{4}\)\s*\d",  # a "<volume> (<year>) <pages>" citation stamp
    re.IGNORECASE,
)


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


def _looks_title_shaped(candidate: str) -> bool:
    if len(candidate) < _MIN_FALLBACK_TITLE_LEN:
        return False
    if _FALLBACK_TITLE_SKIP_RE.search(candidate):
        return False
    digit_ratio = sum(c.isdigit() for c in candidate) / len(candidate)
    return digit_ratio <= 0.05


_MAX_TITLE_CONTINUATION_LINES = 3


def _fallback_title(pages: list[LoadedPage]) -> str | None:
    """Best-effort title when the PDF has no Title metadata: the first
    reasonably long, title-shaped line of page 1 -- skipping publisher
    boilerplate (see _FALLBACK_TITLE_SKIP_RE) and lines too digit-heavy to
    plausibly be a title (a real title is prose; a mis-extracted running
    header or citation stamp is usually thick with page numbers and years).

    A long title commonly wraps onto further PDF lines before the author
    list starts (observed live: a 3-line title, "REAL-TIME STUDENT
    ATTENDANCE" / "SYSTEM USING FACE RECOGNITION AND" / "CLOUD
    INTEGRATION" -- merging only one continuation line cut it off mid-
    phrase) -- keep merging while the line built so far doesn't already
    end a sentence and the next line is itself title-shaped and has no
    comma (an author byline always does, "Firstname Lastname, Firstname
    Lastname"), up to a small cap so a genuinely title-shaped author line
    can never be swallowed indefinitely. Never guesses authors."""
    for page in pages:
        lines = [line.strip() for line in page.text.splitlines()]
        for i, candidate in enumerate(lines):
            if not _looks_title_shaped(candidate):
                continue
            merged = candidate
            next_index = i + 1
            extra_lines = 0
            while (
                extra_lines < _MAX_TITLE_CONTINUATION_LINES
                and not merged.endswith((".", "?", "!"))
                and next_index < len(lines)
            ):
                next_line = lines[next_index]
                if "," in next_line or not _looks_title_shaped(next_line):
                    break
                merged = f"{merged} {next_line}"
                next_index += 1
                extra_lines += 1
            return merged
    return None


@dataclass(frozen=True)
class ParsedPdf:
    meta: PdfFileMeta
    document: ParsedDocument
    chunks: list[PaperChunk]


_WORD_PREFIX_RE = re.compile(r"^microsoft (?:word|powerpoint) - ", re.IGNORECASE)
_FILE_EXT_RE = re.compile(r"\.(?:docx?|pdf|tex|odt|rtf)$", re.IGNORECASE)


def _usable_metadata_title(title: str | None) -> str | None:
    """The PDF's embedded title, unless it is a file name rather than a
    title ("Experiments-in-Agentic-AI-for-ScienceV2", "Microsoft Word -
    draft.docx" -- observed on real uploads): then the title printed on the
    first page is used."""
    if not title:
        return None
    cleaned = _FILE_EXT_RE.sub("", _WORD_PREFIX_RE.sub("", title.strip())).strip()
    if not cleaned or " " not in cleaned:
        return None
    return cleaned


def _filename_title(title: str | None) -> str | None:
    """A file-name title made readable, when the first page offers none."""
    if not title:
        return None
    readable = " ".join(re.split(r"[-_]+", _FILE_EXT_RE.sub("", _WORD_PREFIX_RE.sub("", title.strip()))))
    return readable.strip() or None


_MAX_ABSTRACT_CHARS = 4000


def _abstract_of(full_text: str, sections: list[Section]) -> str | None:
    """The text of the PDF's Abstract section, without its label."""
    section = next((s for s in sections if s.title.strip().lower() == "abstract"), None)
    if section is None:
        return None
    text = clean_abstract(" ".join(full_text[section.char_start : section.char_end].split()))
    return text[:_MAX_ABSTRACT_CHARS] or None


def parse_pdf(
    paper_id: str, pdf_bytes: bytes, filename: str, settings: Settings, *, meta: PdfFileMeta | None = None
) -> ParsedPdf:
    """Validate and read one PDF into its document and chunks, without
    storing anything: an upload becomes a new paper from this, and a paper
    found by discovery gains its full text from it (services/fulltext)."""
    meta = meta or validate_upload(pdf_bytes, filename, settings)
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

    title = _usable_metadata_title(raw.title) or _fallback_title(raw.pages) or _filename_title(raw.title) or filename
    first_page = raw.pages[0].text if raw.pages else ""
    document = ParsedDocument(
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
        doi=find_doi(first_page, raw.margin_text),
        abstract=_abstract_of(full_text, sections),
    )
    chunks = build_chunks(paper_id, full_text, sections, tables, page_ranges, settings)
    return ParsedPdf(meta=meta, document=document, chunks=chunks)


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

    doc = parse_pdf(paper_id, pdf_bytes, filename, settings, meta=meta)
    parsed = doc.document
    paper_orm = repo.paper_from_ingest(
        paper_id=paper_id,
        meta=meta,
        parsed=parsed,
        pdf_path=str(pdf_path),
        title_hash=_title_hash(parsed.title or filename),
    )
    if paper_orm.doi and repo.doi_holder(db, paper_orm.doi) is not None:
        paper_orm.doi = None  # discovery already holds this article under its DOI
    repo.save_paper(db, paper_orm)
    repo.save_chunks(db, doc.chunks)

    return IngestResult(
        paper_id=paper_id,
        parse_confidence=parsed.parse_confidence,
        sections=parsed.sections,
        tables=parsed.tables,
        references=parsed.references,
        warnings=parsed.warnings,
        chunk_count=len(doc.chunks),
        deduplicated=False,
    )
