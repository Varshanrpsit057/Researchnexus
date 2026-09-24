from __future__ import annotations

import os
from collections.abc import Callable

import pytest

# The production relevance model (fastembed) downloads and loads a real
# model; tests stay offline and deterministic with no embedder unless a test
# injects one explicitly. Env vars outrank .env, and Settings(_env_file=None)
# still reads them.
os.environ.setdefault("RESEARCHNEXUS_DISCOVERY_EMBEDDER", "none")

from tests.fixtures.make_fixtures import (
    make_corrupt_pdf,
    make_duplicate_text_pdf,
    make_encrypted_pdf,
    make_multi_page_pdf,
    make_normal_paper_pdf,
    make_not_a_pdf_bytes,
    make_scanned_pdf,
    make_two_column_paper_pdf,
)


@pytest.fixture(scope="session")
def normal_paper_pdf_bytes() -> bytes:
    return make_normal_paper_pdf()


@pytest.fixture(scope="session")
def two_column_paper_pdf_bytes() -> bytes:
    return make_two_column_paper_pdf()


@pytest.fixture(scope="session")
def scanned_pdf_bytes() -> bytes:
    return make_scanned_pdf()


@pytest.fixture(scope="session")
def duplicate_text_pdf_bytes() -> bytes:
    return make_duplicate_text_pdf()


@pytest.fixture(scope="session")
def encrypted_pdf_bytes() -> bytes:
    return make_encrypted_pdf()


@pytest.fixture(scope="session")
def corrupt_pdf_bytes() -> bytes:
    return make_corrupt_pdf()


@pytest.fixture(scope="session")
def not_a_pdf_bytes() -> bytes:
    return make_not_a_pdf_bytes()


@pytest.fixture()
def multi_page_pdf_factory() -> Callable[[int], bytes]:
    return make_multi_page_pdf
