"""Synthetic PDF fixtures for Phase 2 ingestion tests.

We generate PDFs programmatically (reportlab) instead of bundling binary
sample files: it is deterministic, needs no network access, and lets each
test target one specific structural property (two columns, no text layer,
encrypted, truncated/corrupt).

reportlab is a **test-only** dependency (see pyproject.toml `[project.
optional-dependencies].dev`) — it is never imported by application code.
"""

from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

_STYLES = getSampleStyleSheet()
_BODY = _STYLES["BodyText"]
_H1 = ParagraphStyle("H1", parent=_STYLES["Heading1"], fontSize=13, spaceBefore=10, spaceAfter=6)

_LOREM = (
    "Retrieval augmented generation combines a parametric language model with "
    "a non parametric retriever over an external corpus of documents to reduce "
    "hallucination and improve factual grounding for knowledge intensive tasks. "
) * 5


def _running_header_footer(canvas_: canvas.Canvas, doc: BaseDocTemplate) -> None:
    canvas_.saveState()
    canvas_.setFont("Helvetica", 8)
    canvas_.drawCentredString(doc.pagesize[0] / 2, doc.pagesize[1] - 0.5 * inch, "ResearchNexus Synthetic Test Paper")
    canvas_.drawCentredString(doc.pagesize[0] / 2, 0.5 * inch, f"Page {doc.page}")
    canvas_.restoreState()


def make_normal_paper_pdf() -> bytes:
    """A single-column paper with numbered sections, a table, and references."""
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.9 * inch,
        rightMargin=0.9 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
        title="ResearchNexus: A Synthetic Test Paper on Retrieval-Augmented Generation",
        author="A. Author, B. Coauthor",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="single")
    doc.addPageTemplates([PageTemplate(id="Single", frames=[frame], onPage=_running_header_footer)])

    story = [
        Paragraph("ResearchNexus: A Synthetic Test Paper on Retrieval-Augmented Generation", _H1),
        Spacer(1, 10),
        Paragraph("Abstract", _H1),
        Paragraph("This synthetic paper is used to test PDF ingestion. " + _LOREM, _BODY),
        Paragraph("1 Introduction", _H1),
        Paragraph(_LOREM, _BODY),
        Paragraph("2 Related Work", _H1),
        Paragraph(_LOREM, _BODY),
        Paragraph("3 Method", _H1),
        Paragraph(_LOREM, _BODY),
        Paragraph("Table 1: Main results on the benchmark.", _BODY),
    ]
    table_data = [
        ["Method", "Dataset", "F1"],
        ["BM25", "LitSearch", "42.1"],
        ["Dense + rerank", "LitSearch", "58.6"],
    ]
    table = Table(table_data)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
            ]
        )
    )
    story.append(table)
    story += [
        Paragraph("4 Experiments", _H1),
        Paragraph(_LOREM, _BODY),
        Paragraph("5 Conclusion", _H1),
        Paragraph(_LOREM, _BODY),
        Paragraph("Limitations", _H1),
        Paragraph(
            "This synthetic paper does not evaluate on out-of-domain benchmarks "
            "and leaves latency measurement to future work.",
            _BODY,
        ),
        Paragraph("Future Work", _H1),
        Paragraph("Future work includes evaluating on additional scientific domains.", _BODY),
        Paragraph("References", _H1),
    ]
    for i in range(1, 6):
        story.append(Paragraph(f"[{i}] A. Author et al. A paper about topic {i}. Conf. on Testing, 2020.", _BODY))
    doc.build(story)
    return buf.getvalue()


def make_two_column_paper_pdf() -> bytes:
    """A two-column paper: exercises column-aware reading-order extraction."""
    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=LETTER,
        leftMargin=0.7 * inch,
        rightMargin=0.7 * inch,
        topMargin=0.9 * inch,
        bottomMargin=0.9 * inch,
    )
    gutter = 0.3 * inch
    col_width = (doc.width - gutter) / 2
    left = Frame(doc.leftMargin, doc.bottomMargin, col_width, doc.height, id="left")
    right = Frame(doc.leftMargin + col_width + gutter, doc.bottomMargin, col_width, doc.height, id="right")
    doc.addPageTemplates([PageTemplate(id="TwoCol", frames=[left, right], onPage=_running_header_footer)])

    story = [
        Paragraph("Two-Column Synthetic Paper", _H1),
        Paragraph("1 Introduction", _H1),
        Paragraph("INTROSTART " + _LOREM * 10, _BODY),
        Paragraph("2 Method", _H1),
        Paragraph("METHODSTART " + _LOREM * 10, _BODY),
        Paragraph("3 Results", _H1),
        Paragraph("RESULTSTART " + _LOREM * 10, _BODY),
    ]
    doc.build(story)
    return buf.getvalue()


def make_scanned_pdf() -> bytes:
    """A page with only vector graphics -- no extractable text (no text layer)."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.rect(50, 50, 400, 600)
    c.line(50, 50, 450, 650)
    c.showPage()
    c.save()
    return buf.getvalue()


def make_encrypted_pdf(password: str = "secret") -> bytes:
    base = make_normal_paper_pdf()
    reader = PdfReader(io.BytesIO(base))
    writer = PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.encrypt(password)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def make_corrupt_pdf() -> bytes:
    """A PDF with a valid header but a destroyed xref/trailer."""
    good = make_normal_paper_pdf()
    return good[: len(good) // 3]


def make_not_a_pdf_bytes() -> bytes:
    return b"This is a plain text file pretending to be a PDF upload. " * 20


def make_multi_page_pdf(n_pages: int) -> bytes:
    """A simple n-page PDF (single short paragraph per page) for page-count limit tests."""
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=LETTER)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    doc.addPageTemplates([PageTemplate(id="P", frames=[frame])])
    story: list[object] = []
    for i in range(n_pages):
        story.append(Paragraph(f"Page {i + 1} of a multi-page fixture.", _BODY))
        story.append(Spacer(1, 500))
    doc.build(story)
    return buf.getvalue()
