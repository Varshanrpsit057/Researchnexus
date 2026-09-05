from __future__ import annotations

from app.config import Settings
from app.services.ingest.cleaner import clean_pages
from app.services.ingest.pdf_loader import LoadedPage, load_pdf
from app.services.ingest.table_extractor import extract_table_blocks


def test_extracts_caption_and_raw_text_from_real_fixture(normal_paper_pdf_bytes: bytes) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    raw = load_pdf(normal_paper_pdf_bytes, settings)
    cleaned_pages, _full_text, _ranges = clean_pages([p.text for p in raw.pages])
    blocks = extract_table_blocks(raw.pages, cleaned_pages)
    assert len(blocks) >= 1
    block = blocks[0]
    assert block.caption is not None and "Table 1" in block.caption
    assert "BM25" in block.raw_text
    assert "F1" in block.raw_text


def test_skips_tables_that_are_entirely_empty() -> None:
    page = LoadedPage(number=1, text="Table 1: nothing here", tables=[[[None, None], [None, None]]])
    blocks = extract_table_blocks([page], [page.text])
    assert blocks == []


def test_multiple_tables_on_one_page_paired_by_order() -> None:
    page_text = "Table 1: first table\nsome text\nTable 2: second table\n"
    tables: list[list[list[str | None]]] = [
        [["a", "b"], ["1", "2"]],
        [["c", "d"], ["3", "4"]],
    ]
    page = LoadedPage(number=1, text=page_text, tables=tables)
    blocks = extract_table_blocks([page], [page_text])
    assert len(blocks) == 2
    assert blocks[0].caption is not None and "first table" in blocks[0].caption
    assert blocks[1].caption is not None and "second table" in blocks[1].caption
    assert blocks[0].order == 0
    assert blocks[1].order == 1


def test_missing_caption_leaves_caption_none() -> None:
    page = LoadedPage(number=2, text="no caption line here", tables=[[["x", "y"], ["1", "2"]]])
    blocks = extract_table_blocks([page], [page.text])
    assert len(blocks) == 1
    assert blocks[0].caption is None
    assert blocks[0].page == 2
