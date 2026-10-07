"""A PubMed Central article's text from Europe PMC's full-text XML (JATS).

Europe PMC serves the open-access subset of PubMed Central as structured
XML through its REST API -- the documented way to read those articles
programmatically (its PDF links refuse scripted clients). The structure is
explicit, so the sections are taken from it rather than guessed from line
shapes: the abstract, each body section under its own heading (nested ones
flattened in order), and the reference list. Figures, tables and formulas
are left out: they are not prose, as a PDF's table grids are kept out of
the prose chunks.
"""

from __future__ import annotations

import re
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as ET

from app.domain.paper import Section

_SKIP = {"fig", "table-wrap", "disp-formula", "inline-formula", "supplementary-material", "xref", "label", "title"}
_WS = re.compile(r"\s+")


class NotAnArticle(ValueError):
    """The XML has no article body to read."""


def _text(el: Element) -> str:
    """An element's prose: its text and its children's, skipping what isn't prose."""
    parts: list[str] = [el.text or ""]
    for child in el:
        if _local(child.tag) not in _SKIP:
            parts.append(_text(child))
        parts.append(child.tail or "")
    return _WS.sub(" ", "".join(parts)).strip()


def _local(tag: object) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _paragraphs(el: Element) -> list[str]:
    return [t for p in el if _local(p.tag) == "p" and (t := _text(p))]


def _sections(sec: Element, out: list[tuple[str, list[str]]]) -> None:
    title = next((_text(c) for c in sec if _local(c.tag) == "title"), "") or "Untitled section"
    paragraphs = _paragraphs(sec)
    if paragraphs:
        out.append((title, paragraphs))
    for child in sec:
        if _local(child.tag) == "sec":
            _sections(child, out)


def jats_document(xml: str) -> tuple[str, list[Section]]:
    """The article's text and its sections (offsets into that text). No page
    numbers: XML has none, and none is made up."""
    root = ET.fromstring(xml)
    body = root.find(".//body")
    if body is None:
        raise NotAnArticle("no <body> in the article XML")

    blocks: list[tuple[str, list[str]]] = []
    abstract = root.find(".//front//abstract")
    if abstract is not None:
        paragraphs = _paragraphs(abstract) or [t for s in abstract if _local(s.tag) == "sec" for t in _paragraphs(s)]
        if paragraphs:
            blocks.append(("Abstract", paragraphs))
    for child in body:
        if _local(child.tag) == "sec":
            _sections(child, blocks)
        elif _local(child.tag) == "p" and (t := _text(child)):
            blocks.append(("Body", [t]))
    references = [t for ref in root.iterfind(".//back//ref") if (t := _text(ref))]
    if references:
        blocks.append(("References", references))

    text = ""
    sections: list[Section] = []
    for order, (title, paragraphs) in enumerate(blocks):
        start = len(text)
        text += title + "\n" + "\n\n".join(paragraphs) + "\n\n"
        sections.append(Section(title=title, order=order, char_start=start, char_end=len(text), page_start=1, page_end=1))
    if not any(s.title not in {"Abstract", "References"} for s in sections):
        raise NotAnArticle("the article XML has no body text")
    return text, sections
