"""Reads a `.docx` back, independently of the writer: its tables as rows of
cells, each cell its paragraphs' text. Used by the export's tests, and by the
Compare page's Playwright check (`python -m tests.docx_reader FILE`)."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from dataclasses import asdict, dataclass
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


@dataclass
class DocxContent:
    parts: list[str]
    paragraphs: list[str]  # body paragraphs outside tables
    tables: list[list[list[list[str]]]]  # table -> row -> cell -> paragraph texts
    header_rows: list[int]  # per table: rows marked to repeat on each page
    landscape: bool


def _para_text(p: ET.Element) -> str:
    out: list[str] = []
    for el in p.iter():
        if el.tag == f"{W}t":
            out.append(el.text or "")
        elif el.tag == f"{W}br":
            out.append("\n")
    return "".join(out)


def read_docx(data: bytes) -> DocxContent:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = z.namelist()
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    assert body is not None, "no document body"
    paragraphs: list[str] = []
    tables: list[list[list[list[str]]]] = []
    header_rows: list[int] = []
    for child in body:
        if child.tag == f"{W}p":
            paragraphs.append(_para_text(child))
        elif child.tag == f"{W}tbl":
            rows = child.findall(f"{W}tr")
            tables.append([[[_para_text(p) for p in tc.findall(f"{W}p")] for tc in tr.findall(f"{W}tc")] for tr in rows])
            header_rows.append(sum(1 for tr in rows if tr.find(f"{W}trPr/{W}tblHeader") is not None))
    size = body.find(f"{W}sectPr/{W}pgSz")
    landscape = size is not None and size.get(f"{W}orient") == "landscape"
    return DocxContent(parts=parts, paragraphs=paragraphs, tables=tables, header_rows=header_rows, landscape=landscape)


if __name__ == "__main__":
    with open(sys.argv[1], "rb") as f:
        # ASCII-safe: escapes survive any console code page
        print(json.dumps(asdict(read_docx(f.read()))))
