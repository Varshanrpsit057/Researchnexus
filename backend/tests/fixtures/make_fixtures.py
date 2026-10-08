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


def make_duplicate_text_pdf() -> bytes:
    """A page whose every line is drawn twice, offset by roughly half a
    line height -- reproducing a publisher-typesetting duplicate-text-block
    artifact observed live in a real ScienceDirect PDF (every line of the
    abstract came back from extraction duplicated, immediately adjacent to
    itself). Low-level canvas drawing, not platypus flow, since the point
    is exact control over each line's vertical position."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica", 11)
    lines = [
        "This paper investigates the effectiveness of a duplicate text block.",
        "Every line below is drawn twice, offset by half a line height.",
        "A correct extractor must not repeat this content in its output.",
    ]
    y = 700.0
    line_height = 14.0
    for line in lines:
        c.drawString(72, y, line)
        c.drawString(72, y - line_height / 2, line)  # the duplicate, offset
        y -= line_height
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


IEEE_DOI = "10.1109/ISCI65687.2025.11167819"
IEEE_ABSTRACT_WORDS = ["Public", "transportation", "within", "university", "campuses", "plays", "an", "important", "role", "in", "student", "mobility.", "Buses", "often", "fail", "to", "adhere", "to", "schedules,", "which", "affects", "time", "management.", "This", "paper", "proposes", "a", "mobile", "application", "that", "tracks", "university", "buses", "in", "real", "time", "using", "GPS."]
_IEEE_LEFT_BODY = ["Students", "rely", "on", "campus", "buses", "to", "move", "between", "faculties", "and", "residential", "colleges", "every", "day.", "Unreliable", "arrival", "times", "increase", "anxiety", "and", "cause", "students", "to", "miss", "the", "start", "of", "classes."]
_IEEE_RIGHT_BODY = ["RIGHTCOLUMN", "begins", "here", "and", "continues", "the", "introduction", "with", "a", "survey", "of", "student", "satisfaction.", "Most", "respondents", "asked", "for", "live", "bus", "locations", "and", "accurate", "arrival", "estimates", "on", "their", "phones."]


def make_ieee_style_pdf() -> bytes:
    """Page 1 of a typical IEEE conference paper, built to reproduce what a
    real one (remediation, 2026-10-02) defeated: a full-width title and a
    three-column author block above two body columns; an inline
    "Abstract—" paragraph and "Keywords—" line instead of headings; words
    set 1.8 pt apart at 9 pt (tighter than a fixed 3 pt tolerance, so a
    naive extractor glues them together); and the DOI printed sideways in
    the left margin."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    width, _height = LETTER

    def words_line(x: float, y: float, words: list[str], font: str = "Helvetica", size: float = 9.0, gap: float = 1.8) -> None:
        c.setFont(font, size)
        for w in words:
            c.drawString(x, y, w)
            x += stringWidth(w, font, size) + gap

    def column(x: float, y: float, words: list[str], col_width: float, size: float = 9.0) -> float:
        line: list[str] = []
        for w in words:
            trial = [*line, w]
            if line and sum(stringWidth(t, "Helvetica", size) for t in trial) + 1.8 * (len(trial) - 1) > col_width:
                words_line(x, y, line, size=size)
                y -= 11
                line = [w]
            else:
                line = trial
        if line:
            words_line(x, y, line, size=size)
            y -= 11
        return y

    c.setFont("Helvetica-Bold", 22)
    c.drawCentredString(width / 2, 740, "OnBoard: A Real-Time Bus Tracking Mobile")
    c.drawCentredString(width / 2, 714, "Application for University Campus")
    c.setFont("Helvetica", 10)
    for x, name, place in ((150, "Syaqir Syamsul", "Universiti Teknologi MARA"), (306, "Mohd Suffian Sulaiman", "Universiti Teknologi MARA"), (462, "Fakhrul Hazman Yusoff", "Sohar University")):
        c.drawCentredString(x, 686, name)
        c.drawCentredString(x, 673, place)

    left_x, right_x, col_w = 54.0, 318.0, 240.0
    y = column(left_x, 630, ["Abstract—" + IEEE_ABSTRACT_WORDS[0], *IEEE_ABSTRACT_WORDS[1:]], col_w)
    y = column(left_x, y - 6, ["Keywords—bus", "tracking,", "GPS,", "mobile", "application"], col_w)
    c.setFont("Helvetica", 10)
    c.drawString(left_x + 90, y - 12, "I. INTRODUCTION")
    column(left_x, y - 30, _IEEE_LEFT_BODY * 3, col_w)
    column(right_x, 630, _IEEE_RIGHT_BODY * 4, col_w)

    c.saveState()
    c.translate(24, 300)
    c.rotate(90)
    c.setFont("Helvetica", 7)
    c.drawString(0, 0, f"2025 IEEE Conference | DOI: {IEEE_DOI}")
    c.restoreState()

    c.showPage()
    c.save()
    return buf.getvalue()


def make_offset_columns_pdf() -> bytes:
    """A two-column references page whose columns don't share baselines
    (2026-10-07: a real arXiv paper's reference list): the left column at
    11 pt leading under a "REFERENCES" heading, the right at 8.7 pt from a
    slightly different top. Hardly any line has text on both sides of the
    gutter, which a both-sides test took for one column -- the heading was
    read as part of the right column's first line and the references were
    never found."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(140, 742, "REFERENCES")
    c.setFont("Helvetica", 8)
    y = 724.0
    for n in range(1, 31):
        c.drawString(54, y, f"[{n}] A. Author{n} and B. Writer, Left entry title {n}, 2021.")
        y -= 11.0
    y = 739.0
    for n in range(31, 71):
        c.drawString(318, y, f"[{n}] C. Person{n}, Right entry title {n}, 2022.")
        y -= 8.7
    c.showPage()
    c.save()
    return buf.getvalue()
