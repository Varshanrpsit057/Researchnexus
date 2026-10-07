"""The comparison table model and its Word export (remediation Phase 12):
the exported table is the page's table -- same headings, rows, cells and
order, complete text, a real Word table."""

from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from io import BytesIO
from xml.etree import ElementTree as ET

import pytest

from app.domain.comparison import (
    CellStatus,
    Comparison,
    ComparisonCell,
    ComparisonRow,
    ComparisonSchema,
)
from app.domain.profile import SourceSpan
from app.services.synthesis.comparison_table import (
    PaperRecord,
    UnknownPapers,
    build_table,
    field_label,
    short_authors,
)
from app.services.synthesis.docx_export import comparison_docx, docx_filename
from tests.docx_reader import read_docx

LONG_TITLE = (
    "Dense Passage Retrieval for Open-Domain Question Answering: A Very Long Title That Goes On Well Past Any "
    "Sensible Column Width, Including <Angle Brackets> & Ampersands, \"Quotes\" and Ünïcödé"
)


def _span(pid: str, quote: str) -> SourceSpan:
    return SourceSpan(paper_id=pid, char_start=0, char_end=len(quote), quote=quote)


def _found(col: str, pid: str, text: str, *, grounding: str = "full_text", conflicting: list[str] | None = None) -> ComparisonCell:
    return ComparisonCell(column=col, text=text, span=_span(pid, text), claim_id="clm", grounding=grounding, conflicting=conflicting or [])


def _empty(col: str, status: CellStatus, *, grounding: str = "full_text") -> ComparisonCell:
    return ComparisonCell(column=col, status=status, grounding=grounding)


def _comparison(n_papers: int = 3) -> Comparison:
    pids = [f"pap_{i}" for i in range(n_papers)]
    cols = ["problem", "method", "dataset", "custom thing"]
    rows = []
    for i, pid in enumerate(pids):
        if i == 0:
            cells = {
                "problem": _found("problem", pid, "open-domain question answering"),
                "method": _found("method", pid, "dense retrieval\nwith a dual encoder", conflicting=["BM25", "TF-IDF"]),
                "dataset": _found("dataset", pid, "Natural Questions & TriviaQA"),
                "custom thing": _empty("custom thing", CellStatus.NOT_STATED),
            }
        elif i == 1:
            g = "abstract"
            cells = {
                "problem": _found("problem", pid, "sparse retrieval \x07baseline", grounding=g),
                "method": _empty("method", CellStatus.UNSUPPORTED, grounding=g),
                "dataset": _empty("dataset", CellStatus.NOT_EXTRACTED, grounding=g),
                "custom thing": _empty("custom thing", CellStatus.UNKNOWN, grounding=g),
            }
        else:
            cells = {c: _empty(c, CellStatus.NO_TEXT) for c in cols}
        rows.append(ComparisonRow(paper_id=pid, cells=cells))
    return Comparison(
        comparison_id="cmp_1",
        workspace_id="ws_1",
        column_schema=ComparisonSchema(columns=cols),
        paper_ids=pids,
        rows=rows,
        created_at=datetime(2026, 9, 30, 14, 5, tzinfo=timezone.utc),
    )


RECORDS = {
    "pap_0": PaperRecord(title=LONG_TITLE, authors=["V. Karpukhin", "B. Oguz", "S. Min"], year=2020, publisher="ACL"),
    "pap_1": PaperRecord(title="BM25 Revisited", authors=["S. Robertson", "H. Zaragoza"], year=2009),
    "pap_2": PaperRecord(title="Untitled Notes", authors=[], year=None),
    "pap_3": PaperRecord(title="Fourth", authors=["A. Solo"], year=2021),
}


def _table(n: int = 3, **kw):  # noqa: ANN003,ANN202
    return build_table(_comparison(n), records=RECORDS, members=["pap_0", "pap_1"], seed_paper_id="pap_0", **kw)


# -- the model ---------------------------------------------------------------


def test_short_authors_and_field_labels_read_as_the_page_writes_them() -> None:
    assert short_authors([]) == ""
    assert short_authors(["A"]) == "A"
    assert short_authors(["A", "B"]) == "A and B"
    assert short_authors(["A", "B", "C"]) == "A et al."
    assert field_label("problem") == "Research problem"
    assert field_label("dataset") == "Datasets"
    assert field_label("custom thing") == "Custom thing"


def test_table_keeps_the_comparison_order_full_titles_and_every_cell_reason() -> None:
    t = _table()
    assert [p.paper_id for p in t.papers] == ["pap_0", "pap_1", "pap_2"]
    assert t.header == ["Field", LONG_TITLE, "BM25 Revisited", "Untitled Notes"]
    assert [r.label for r in t.rows] == ["Research problem", "Method", "Datasets", "Custom thing"]
    assert [p.kind for p in t.papers] == ["seed", "member", "connected"]
    assert t.papers[0].meta == "V. Karpukhin et al. · 2020 · ACL · Full text"  # who published it, too
    assert t.papers[1].meta == "S. Robertson and H. Zaragoza · 2009 · Abstract only"
    assert t.papers[2].meta == "No text · No longer in the workspace"

    method = t.rows[1]
    assert method.cells[0].text == "dense retrieval\nwith a dual encoder"
    assert method.cells[0].note == "The same passage also says: BM25, TF-IDF"
    assert method.cells[1].text == "Unverified" and method.cells[1].status == "unsupported"
    assert t.rows[2].cells[1].text == "Not read"
    assert t.rows[3].cells[0].text == "Not stated"
    assert t.rows[3].cells[1].text == "Not found"
    assert t.rows[0].cells[2].text == "No text to read"


def test_table_shows_only_the_chosen_papers_in_the_comparisons_own_order() -> None:
    t = _table(paper_ids=["pap_2", "pap_0"])
    assert [p.paper_id for p in t.papers] == ["pap_0", "pap_2"]
    assert all(len(r.cells) == 2 for r in t.rows)
    with pytest.raises(UnknownPapers):
        _table(paper_ids=["pap_0", "pap_nope"])


# -- the Word document ------------------------------------------------------


def _expected_grid(t) -> list[list[list[str]]]:  # noqa: ANN001
    head = [["Field"], *([p.title, p.meta] for p in t.papers)]
    return [head, *([[r.label], *(c.lines for c in r.cells)] for r in t.rows)]


def test_docx_is_a_complete_word_package_with_well_formed_parts() -> None:
    data = comparison_docx(_table(), workspace_title="Retrieval & QA")
    with zipfile.ZipFile(BytesIO(data)) as z:
        assert z.testzip() is None
        names = set(z.namelist())
        assert {"[Content_Types].xml", "_rels/.rels", "word/document.xml", "word/styles.xml", "word/_rels/document.xml.rels"} <= names
        for name in names:
            ET.fromstring(z.read(name))  # every part parses
        types = z.read("[Content_Types].xml").decode()
        assert "wordprocessingml.document.main+xml" in types
        assert "<w:drawing" not in z.read("word/document.xml").decode()  # a table, not a picture of one


def test_docx_table_is_the_page_table_cell_for_cell() -> None:
    t = _table()
    doc = read_docx(comparison_docx(t, workspace_title="W"))
    assert len(doc.tables) == 1
    grid = doc.tables[0]
    assert grid == _expected_grid(t)
    # rows x columns: a heading row plus one row per field, a field column plus one per paper
    assert len(grid) == 1 + len(t.rows)
    assert all(len(row) == 1 + len(t.papers) for row in grid)
    assert grid[0][1][0] == LONG_TITLE  # complete, escaped and back again
    assert grid[1][2] == ["sparse retrieval baseline"]  # a control character never breaks the file
    assert doc.header_rows == [1]  # the heading row repeats on every page


def test_docx_keeps_only_the_chosen_columns_and_goes_landscape_when_wide() -> None:
    narrow = read_docx(comparison_docx(_table(paper_ids=["pap_0", "pap_1"]), workspace_title="W"))
    assert [c[0] for c in narrow.tables[0][0]] == ["Field", LONG_TITLE, "BM25 Revisited"]
    assert narrow.landscape is False
    wide_table = build_table(_comparison(4), records=RECORDS, members=["pap_0"], seed_paper_id="pap_0")
    wide = read_docx(comparison_docx(wide_table, workspace_title="W"))
    assert wide.landscape is True
    assert wide.tables[0] == _expected_grid(wide_table)


def test_docx_says_what_it_is_and_explains_only_the_empty_cells_it_has() -> None:
    doc = read_docx(comparison_docx(_table(paper_ids=["pap_0"]), workspace_title="My <Workspace>"))
    assert doc.paragraphs[0] == "Comparison: My <Workspace>"
    assert "1 papers side by side, 4 fields. Compared 30 September 2026, 14:05 UTC." in doc.paragraphs[1]
    assert "3 of 4 values" in doc.paragraphs[1]
    legend = [p for p in doc.paragraphs if ": " in p and p.split(":")[0] in {"Not stated", "Unverified", "Not read", "Not found", "No text to read"}]
    assert legend == ["Not stated: The paper's text was read and does not state this."]


def test_docx_filename_is_plain() -> None:
    assert docx_filename('Retrieval: "dense" / sparse?') == "Comparison - Retrieval dense  sparse.docx"
    assert docx_filename("???") == "Comparison - workspace.docx"
