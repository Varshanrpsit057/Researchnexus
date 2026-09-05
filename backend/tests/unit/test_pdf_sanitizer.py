from __future__ import annotations

import pytest

from app.config import Settings
from app.security.pdf_sanitizer import (
    FileTooLarge,
    PdfEncrypted,
    PdfInvalid,
    PdfScanned,
    TooManyPages,
    UnsupportedMediaType,
    validate_upload,
)


@pytest.fixture()
def settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_normal_pdf_passes_validation(normal_paper_pdf_bytes: bytes, settings: Settings) -> None:
    meta = validate_upload(normal_paper_pdf_bytes, "paper.pdf", settings)
    assert meta.page_count >= 1
    assert meta.has_text_layer is True
    assert meta.encrypted is False
    assert meta.size_bytes == len(normal_paper_pdf_bytes)
    assert len(meta.sha256) == 64  # hex sha256


def test_oversized_pdf_rejected(normal_paper_pdf_bytes: bytes) -> None:
    tiny_limit = Settings(_env_file=None, max_pdf_mb=0)  # type: ignore[call-arg]
    with pytest.raises(FileTooLarge):
        validate_upload(normal_paper_pdf_bytes, "paper.pdf", tiny_limit)


def test_non_pdf_bytes_rejected(not_a_pdf_bytes: bytes, settings: Settings) -> None:
    with pytest.raises(UnsupportedMediaType):
        validate_upload(not_a_pdf_bytes, "paper.pdf", settings)


def test_wrong_extension_rejected(normal_paper_pdf_bytes: bytes, settings: Settings) -> None:
    with pytest.raises(UnsupportedMediaType):
        validate_upload(normal_paper_pdf_bytes, "paper.docx", settings)


def test_empty_bytes_rejected(settings: Settings) -> None:
    with pytest.raises(UnsupportedMediaType):
        validate_upload(b"", "paper.pdf", settings)


def test_corrupt_pdf_rejected(corrupt_pdf_bytes: bytes, settings: Settings) -> None:
    with pytest.raises(PdfInvalid):
        validate_upload(corrupt_pdf_bytes, "paper.pdf", settings)


def test_encrypted_pdf_rejected(encrypted_pdf_bytes: bytes, settings: Settings) -> None:
    with pytest.raises(PdfEncrypted):
        validate_upload(encrypted_pdf_bytes, "paper.pdf", settings)


def test_scanned_pdf_rejected(scanned_pdf_bytes: bytes, settings: Settings) -> None:
    with pytest.raises(PdfScanned):
        validate_upload(scanned_pdf_bytes, "paper.pdf", settings)


def test_too_many_pages_rejected(multi_page_pdf_factory) -> None:
    data = multi_page_pdf_factory(3)
    strict = Settings(_env_file=None, max_pages=2)  # type: ignore[call-arg]
    with pytest.raises(TooManyPages):
        validate_upload(data, "paper.pdf", strict)


def test_error_codes_match_api_spec(normal_paper_pdf_bytes: bytes) -> None:
    tiny_limit = Settings(_env_file=None, max_pdf_mb=0)  # type: ignore[call-arg]
    try:
        validate_upload(normal_paper_pdf_bytes, "paper.pdf", tiny_limit)
    except FileTooLarge as e:
        assert e.code == "file_too_large"
