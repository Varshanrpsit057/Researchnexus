"""Give a paper the text of a PDF (remediation, 2026-10-02):

- re-read an uploaded paper's stored PDF with the current reader (it fixed
  glued words, two-column first pages and inline abstracts that earlier
  reads got wrong);
- attach a PDF the reader has to a paper discovery found, which otherwise
  has only its abstract (publishers' copies can't be fetched for them).

Either way the paper's text, sections and chunks become the PDF's. What the
paper's record already says (its title, its discovery metadata) stays; the
PDF fills in its abstract and DOI only where the record has none.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.security.pdf_sanitizer import validate_upload
from app.services.ingest.pipeline import ParsedPdf, parse_pdf
from app.services.ingest.pipeline import _title_hash as title_hash_of


class NoStoredPdf(Exception):
    """The paper has no PDF on disk to read again."""


class PaperNotFound(Exception):
    pass


@dataclass(frozen=True)
class TextOutcome:
    paper_id: str
    chunks: int
    sections: int
    abstract_found: bool
    doi: str | None


def _fill_from_pdf(db: Session, paper_id: str, parsed: ParsedPdf) -> TextOutcome:
    paper = repo.get_paper(db, paper_id)
    assert paper is not None
    doc = parsed.document
    if doc.abstract:
        paper.abstract = doc.abstract  # the paper's own words
    if not paper.doi and doc.doi and repo.doi_holder(db, doc.doi) is None:
        paper.doi = doc.doi
    if not paper.authors and doc.authors:
        paper.authors = doc.authors
    db.commit()
    return TextOutcome(
        paper_id=paper_id,
        chunks=len(parsed.chunks),
        sections=len(doc.sections),
        abstract_found=doc.abstract is not None,
        doi=paper.doi,
    )


def reread_stored_pdf(db: Session, paper_id: str, settings: Settings) -> TextOutcome:
    """Read an uploaded paper's stored PDF again with the current reader."""
    paper = repo.get_paper(db, paper_id)
    if paper is None:
        raise PaperNotFound(paper_id)
    path = Path(paper.pdf_path) if paper.pdf_path else None
    if path is None or not path.is_file():
        raise NoStoredPdf(paper_id)
    data = path.read_bytes()
    parsed = parse_pdf(paper_id, data, path.name, settings)
    repo.replace_text(db, paper_id, parsed)
    new_title = parsed.document.title
    if new_title and new_title != paper.title and new_title != path.name:
        # an upload's title is the PDF's: an earlier, worse read of it is replaced
        paper.title = new_title
        paper.title_hash = title_hash_of(new_title)
        db.commit()
    return _fill_from_pdf(db, paper_id, parsed)


def attach_pdf(db: Session, paper_id: str, pdf_bytes: bytes, filename: str, settings: Settings) -> TextOutcome:
    """A PDF the reader supplies becomes a paper's full text."""
    paper = repo.get_paper(db, paper_id)
    if paper is None:
        raise PaperNotFound(paper_id)
    meta = validate_upload(pdf_bytes, filename, settings)  # PdfValidationError for anything that isn't a readable PDF
    pdf_path = settings.pdf_storage_dir() / f"{paper_id}.pdf"
    pdf_path.write_bytes(pdf_bytes)
    parsed = parse_pdf(paper_id, pdf_bytes, filename, settings, meta=meta)
    doc = parsed.document
    repo.attach_full_text(
        db,
        paper_id,
        pdf_path=str(pdf_path),
        sha256=meta.sha256,
        page_count=doc.page_count,
        parse_confidence=doc.parse_confidence.value,
        sections=[s.model_dump(mode="json") for s in doc.sections],
        tables=[t.model_dump(mode="json") for t in doc.tables],
        references=[r.model_dump(mode="json") for r in doc.references],
        warnings=doc.warnings,
        chunks=parsed.chunks,
        source="upload",
        url="",
    )
    # a discovered paper keeps the abstract its source gave it when the PDF has none
    return _fill_from_pdf(db, paper_id, parsed)
