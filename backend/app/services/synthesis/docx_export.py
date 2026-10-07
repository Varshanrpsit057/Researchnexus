"""The comparison table as a Word document (remediation Phase 12).

A real `.docx` (Office Open XML, written with the standard library's
`zipfile`): one Word table with the comparison's exact header row, rows,
cell text and order -- the model `comparison_table.build_table` gives the
page. Nothing is truncated or drawn as an image; the header row repeats on
every page, and a wide comparison is laid out in landscape.
"""

from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from app.services.synthesis.comparison_table import (
    CORNER,
    EMPTY_LABEL,
    EMPTY_MEANING,
    ComparisonTable,
    TableCell,
    clean,
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_RELS = "http://schemas.openxmlformats.org/package/2006/relationships"

# A4, in twentieths of a point; 0.75 in margins.
_PAGE_SHORT, _PAGE_LONG, _MARGIN = 11906, 16838, 1080
_FIELD_COL = 1900
_LANDSCAPE_FROM = 4  # papers; from here a portrait page makes columns too narrow to read

_EMPTY_COLOUR = "6B7280"
_META_COLOUR = "4B5563"
_HEAD_FILL = "E8EEF7"
_FIELD_FILL = "F4F6FA"
_BORDER = "B6C2D6"


def _text(value: str) -> str:
    return escape(clean(value))


def _run(text: str, *, bold: bool = False, italic: bool = False, size: int | None = None, colour: str | None = None) -> str:
    props = "".join(
        [
            "<w:b/>" if bold else "",
            "<w:i/>" if italic else "",
            f'<w:color w:val="{colour}"/>' if colour else "",
            f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else "",
        ]
    )
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    # line breaks inside a value stay line breaks
    pieces = _text(text).split("\n")
    body = "<w:br/>".join(f'<w:t xml:space="preserve">{p}</w:t>' for p in pieces)
    return f"<w:r>{rpr}{body}</w:r>"


def _para(runs: str, *, style: str | None = None, after: int | None = None, keep_next: bool = False) -> str:
    props = "".join(
        [
            f'<w:pStyle w:val="{style}"/>' if style else "",
            "<w:keepNext/>" if keep_next else "",
            f'<w:spacing w:before="0" w:after="{after}"/>' if after is not None else "",
        ]
    )
    ppr = f"<w:pPr>{props}</w:pPr>" if props else ""
    return f"<w:p>{ppr}{runs}</w:p>"


def _tc(width: int, paragraphs: str, *, fill: str | None = None) -> str:
    shade = f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>' if fill else ""
    return f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>{paragraphs}</w:tc>'


def _value_cell(cell: TableCell, width: int) -> str:
    if cell.status == "found":
        paras = _para(_run(cell.text), after=0 if cell.note else None)
        if cell.note:
            paras += _para(_run(cell.note, italic=True, size=17, colour=_META_COLOUR))
    else:
        paras = _para(_run(cell.text, italic=True, colour=_EMPTY_COLOUR))
    return _tc(width, paras)


def _table(table: ComparisonTable, text_width: int) -> str:
    n = len(table.papers)
    paper_col = max(1, (text_width - _FIELD_COL) // max(n, 1))
    grid = f'<w:gridCol w:w="{_FIELD_COL}"/>' + "".join(f'<w:gridCol w:w="{paper_col}"/>' for _ in range(n))
    borders = "".join(
        f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="{_BORDER}"/>'
        for side in ("top", "left", "bottom", "right", "insideH", "insideV")
    )
    tbl_pr = (
        "<w:tblPr>"
        '<w:tblStyle w:val="ComparisonTable"/>'
        f'<w:tblW w:w="{_FIELD_COL + paper_col * n}" w:type="dxa"/>'
        f"<w:tblBorders>{borders}</w:tblBorders>"
        '<w:tblLayout w:type="fixed"/>'
        '<w:tblCellMar><w:top w:w="70" w:type="dxa"/><w:left w:w="100" w:type="dxa"/>'
        '<w:bottom w:w="70" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar>'
        '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>'
        "</w:tblPr>"
    )
    head_cells = _tc(_FIELD_COL, _para(_run(CORNER, bold=True)), fill=_HEAD_FILL) + "".join(
        _tc(
            paper_col,
            _para(_run(p.title, bold=True), after=40) + _para(_run(p.meta, size=17, colour=_META_COLOUR)),
            fill=_HEAD_FILL,
        )
        for p in table.papers
    )
    # the header row repeats on every page, and never splits
    head = f'<w:tr><w:trPr><w:cantSplit/><w:tblHeader/></w:trPr>{head_cells}</w:tr>'
    body = "".join(
        "<w:tr>"
        + _tc(_FIELD_COL, _para(_run(row.label, bold=True)), fill=_FIELD_FILL)
        + "".join(_value_cell(c, paper_col) for c in row.cells)
        + "</w:tr>"
        for row in table.rows
    )
    return f"<w:tbl>{tbl_pr}<w:tblGrid>{grid}</w:tblGrid>{head}{body}</w:tbl>"


def _document(table: ComparisonTable, workspace_title: str) -> str:
    landscape = len(table.papers) >= _LANDSCAPE_FROM
    width, height = (_PAGE_LONG, _PAGE_SHORT) if landscape else (_PAGE_SHORT, _PAGE_LONG)
    text_width = width - 2 * _MARGIN
    compared = table.created_at.astimezone(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    found = sum(1 for r in table.rows for c in r.cells if c.status == "found")
    total = sum(len(r.cells) for r in table.rows)
    intro = (
        f"{len(table.papers)} papers side by side, {len(table.rows)} fields. Compared {compared}. "
        f"{found} of {total} values are stated in the papers' own text; every value is quoted word for word "
        "from a passage of its paper, and every empty cell says why it is empty."
    )
    present = {c.status for r in table.rows for c in r.cells}
    legend = "".join(
        _para(_run(f"{EMPTY_LABEL[s]}: ", bold=True, size=18) + _run(EMPTY_MEANING[s], size=18, colour=_META_COLOUR), after=40)
        for s in EMPTY_MEANING
        if s.value in present
    )
    orient = ' w:orient="landscape"' if landscape else ""
    sect = (
        f'<w:sectPr><w:pgSz w:w="{width}" w:h="{height}"{orient}/>'
        f'<w:pgMar w:top="{_MARGIN}" w:right="{_MARGIN}" w:bottom="{_MARGIN}" w:left="{_MARGIN}" '
        'w:header="540" w:footer="540" w:gutter="0"/></w:sectPr>'
    )
    body = (
        _para(_run(f"Comparison: {workspace_title}"), style="Title")
        + _para(_run(intro, colour=_META_COLOUR), after=200)
        + _table(table, text_width)
        + (_para(_run("Empty cells", bold=True), style="Heading2") + legend if legend else "")
        + sect
    )
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{_W}" xmlns:r="{_R}"><w:body>{body}</w:body></w:document>'


_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{_W}">
<w:docDefaults>
<w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/><w:sz w:val="20"/><w:szCs w:val="20"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="80" w:line="252" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:spacing w:after="120"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:keepNext/><w:spacing w:before="280" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/><w:semiHidden/>
<w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
<w:style w:type="table" w:styleId="ComparisonTable"><w:name w:val="Comparison Table"/><w:basedOn w:val="TableNormal"/>
<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:style>
</w:styles>"""

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

_ROOT_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_PKG_RELS}">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

_DOC_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{_PKG_RELS}">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>ResearchNexus</Application></Properties>"""


def _core(title: str, now: datetime) -> str:
    stamp = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{_text(title)}</dc:title><dc:creator>ResearchNexus</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{stamp}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def comparison_docx(table: ComparisonTable, *, workspace_title: str, now: datetime | None = None) -> bytes:
    """The comparison table as the bytes of a `.docx` file."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", _document(table, workspace_title))
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("docProps/core.xml", _core(f"Comparison: {workspace_title}", now or datetime.now(timezone.utc)))
        z.writestr("docProps/app.xml", _APP)
    return out.getvalue()


def docx_filename(workspace_title: str) -> str:
    """A safe file name: the workspace's title, kept to plain characters."""
    stem = re.sub(r"[^A-Za-z0-9 ._-]+", "", workspace_title).strip(" .")[:80] or "workspace"
    return f"Comparison - {stem}.docx"
