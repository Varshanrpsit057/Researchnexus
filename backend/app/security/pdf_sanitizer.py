"""Upload validation (Stage S1).

Uploaded PDFs are UNTRUSTED DATA (see docs/architecture/
ResearchNexus_Seed_Paper_Research_Trail.md §21 and docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 17). This module performs the
cheap, synchronous checks the API spec maps to 413/415/422 (docs/
architecture/ResearchNexus_API_Specification.md §1.1, §4). The heavier
structural parse (which can also reveal a scanned/garbled document) happens
in the async ingest job — see app/services/ingest/pipeline.py.

Deliberately conservative: nothing here trusts filename or extension alone;
every check also inspects the actual bytes.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.config import Settings

_PDF_MAGIC = b"%PDF-"


class PdfValidationError(Exception):
    """Base class for all upload-validation failures. `code` matches the
    error envelope's `error.code` in the API specification."""

    code: str = "pdf_invalid"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class FileTooLarge(PdfValidationError):
    code = "file_too_large"


class UnsupportedMediaType(PdfValidationError):
    code = "unsupported_media_type"


class PdfInvalid(PdfValidationError):
    code = "pdf_invalid"


class PdfEncrypted(PdfValidationError):
    code = "pdf_encrypted"


class PdfScanned(PdfValidationError):
    code = "pdf_scanned"


class TooManyPages(PdfValidationError):
    """Not enumerated as its own HTTP code in the API spec; surfaced as a
    422 `pdf_invalid` with this message so the client can distinguish it."""

    code = "too_many_pages"


@dataclass(frozen=True)
class PdfFileMeta:
    sha256: str
    size_bytes: int
    page_count: int
    has_text_layer: bool
    encrypted: bool


def _looks_like_pdf(data: bytes, filename: str) -> bool:
    if not filename.lower().endswith(".pdf"):
        return False
    return data[:5] == _PDF_MAGIC


def validate_upload(data: bytes, filename: str, settings: Settings) -> PdfFileMeta:
    """Validate an uploaded file and return metadata, or raise a
    `PdfValidationError` subclass. Never partially trusts the input:
    every branch inspects the bytes, not just the filename."""

    size_mb = len(data) / (1024 * 1024)
    if size_mb > settings.max_pdf_mb:
        raise FileTooLarge(f"file is {size_mb:.1f} MB, limit is {settings.max_pdf_mb} MB")

    if not _looks_like_pdf(data, filename):
        raise UnsupportedMediaType("file is not a valid PDF (bad extension or missing %PDF- header)")

    try:
        reader = PdfReader(io.BytesIO(data))
        encrypted = reader.is_encrypted
    except (PdfReadError, ValueError, OSError) as e:
        raise PdfInvalid(f"could not open PDF: {e}") from e

    if encrypted:
        raise PdfEncrypted("PDF is password-protected")

    try:
        page_count = len(reader.pages)
    except (PdfReadError, ValueError, OSError) as e:
        raise PdfInvalid(f"could not read PDF pages: {e}") from e

    if page_count == 0:
        raise PdfInvalid("PDF has zero pages")
    if page_count > settings.max_pages:
        raise TooManyPages(f"PDF has {page_count} pages, limit is {settings.max_pages}")

    sample = reader.pages[: min(3, page_count)]
    has_text = False
    for page in sample:
        try:
            if (page.extract_text() or "").strip():
                has_text = True
                break
        except Exception:  # noqa: BLE001 - a single bad page must not abort validation
            continue
    if not has_text:
        raise PdfScanned("no extractable text found (scanned or image-only PDF)")

    return PdfFileMeta(
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        page_count=page_count,
        has_text_layer=True,
        encrypted=False,
    )
