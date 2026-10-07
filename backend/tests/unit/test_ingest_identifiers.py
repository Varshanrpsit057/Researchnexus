"""A PDF's own DOI and abstract, read from its text (remediation, 2026-10-02)."""

from __future__ import annotations

from app.config import Settings
from app.services.ingest.identifiers import find_doi
from app.services.ingest.pipeline import parse_pdf
from app.services.ingest.section_splitter import split_sections
from tests.fixtures.make_fixtures import IEEE_ABSTRACT_WORDS, IEEE_DOI, make_ieee_style_pdf


def test_the_doi_is_read_from_the_margin_forwards_or_reversed_and_then_the_first_page() -> None:
    assert find_doi("", "2025 IEEE | DOI: 10.1109/ISCI65687.2025.11167819") == "10.1109/isci65687.2025.11167819"
    # IEEE's sideways stamp, as extraction returned it from a real paper: characters reversed
    assert find_doi("", "91876111.5202.78656ICSI/9011.01 :IOD") == "10.1109/isci65687.2025.11167819"
    assert find_doi("Published in Nature. https://doi.org/10.1038/s41586-021-03819-2.") == "10.1038/s41586-021-03819-2"
    assert find_doi("No identifier on this page.") is None


def test_an_inline_abstract_and_keywords_line_open_their_sections() -> None:
    text = "\n".join([
        "A Paper Title",
        "Abstract�Public transport matters. It is often late.",  # the dash lost in extraction
        "Index Terms—GPS, buses",
        "I. INTRODUCTION",
        "Body text.",
    ])
    titles = [s.title for s in split_sections(text, [(0, len(text))])]
    assert titles == ["Abstract", "Keywords", "I. INTRODUCTION"]
    # a sentence that merely starts with the word is not a heading
    plain = "Abstract thinking is hard\nIntroduction\nMore."
    assert "Abstract" not in [s.title for s in split_sections(plain, [(0, len(plain))])]


def test_an_ieee_first_page_yields_its_abstract_and_doi() -> None:
    doc = parse_pdf("pap_t", make_ieee_style_pdf(), "ieee.pdf", Settings(_env_file=None)).document  # type: ignore[call-arg]
    assert doc.doi == IEEE_DOI.lower()
    assert doc.abstract == " ".join(IEEE_ABSTRACT_WORDS)
    assert [s.title for s in doc.sections][:3] == ["Abstract", "Keywords", "I. INTRODUCTION"]


def test_a_file_name_is_not_taken_for_the_papers_title() -> None:
    from app.services.ingest.pipeline import _filename_title, _usable_metadata_title

    assert _usable_metadata_title("Experiments-in-Agentic-AI-for-ScienceV2") is None  # observed on a real upload
    assert _usable_metadata_title("Microsoft Word - Bus Tracking Final.docx") == "Bus Tracking Final"
    assert _usable_metadata_title("OnBoard: A Real-Time Bus Tracking App") == "OnBoard: A Real-Time Bus Tracking App"
    assert _usable_metadata_title(None) is None
    assert _filename_title("Experiments-in-Agentic-AI-for-ScienceV2") == "Experiments in Agentic AI for ScienceV2"
