"""Display text from parsed papers and search APIs, cleaned (remediation Phase 6).

Paper text reaches ResearchNexus from PDF extraction and from four search
APIs, and each leaves its own debris: an "Abstract" label glued to the first
sentence ("Abstract�In modern..."), a publisher's copyright and licence block
after the last one (on some PDFs doubled or letter-spaced by an overlapping
text layer: "TThhee AAuutthhoorrss", "T h i s i s a n o p e n"), JATS markup,
a keyword list, hyphenated line breaks, ligatures, and U+FFFD where a dash
or apostrophe failed to decode.

Nothing here changes what a text says: it removes what isn't the text and
repairs how it was written down. Quotes kept as evidence are never passed
through it -- a quote must stay verbatim to be found in the paper.
"""

from __future__ import annotations

import html
import re

_LIGATURES = str.maketrans({"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"})
_HYPHEN_BREAK = re.compile(r"(\w)-[ \t]*\n[ \t]*(\w)")
_WS = re.compile(r"\s+")
_LEADING_JUNK = re.compile(r"^[\s:;,.·•*\-\u2013\u2014\ufffd]+")
_TAG = re.compile(r"<[^>]{1,200}>")
# U+FFFD stood for something that failed to decode: judge it by its neighbours
_BAD_APOSTROPHE = re.compile(r"(\w)\ufffd(s|t|re|ve|ll|d)\b")
_BAD_RANGE = re.compile(r"(\d)\ufffd(\d)")
_BAD_DASH = re.compile(r"(\w)\ufffd(\w)")

# the label a parser or an API left in front of the abstract's first sentence:
# "Abstract: ...", "Abstract\n...", "Abstract\ufffdIn ...", "ABSTRACT In ..."
_LABEL = re.compile(r"^\W*(?i:abstract|summary)\s*(?:[:.\-\u2013\u2014\ufffd]+\s*|\n\s*)")
# "Abstract The ..." with only a space: a label unless it starts a name
# ("Abstract Meaning Representation parsing ..." is a sentence, not a label)
_SPACED_LABEL = re.compile(r"^\W*(?i:abstract|summary) +(?P<next>[A-Z][\w\-]*) +(?P<after>\S+)")
_OPENERS = {
    "The", "This", "These", "In", "We", "A", "An", "Our", "It", "Its", "Here", "To", "With", "For", "Despite",
    "Although", "Recent", "Many", "Over", "As", "Since", "While", "However", "Background", "Objective", "Purpose",
}


def _strip_label(text: str) -> str:
    stripped = _LABEL.sub("", text, count=1)
    if stripped != text:
        return stripped
    m = _SPACED_LABEL.match(text)
    if m and (m["next"] in _OPENERS or m["after"][:1].islower()):
        return text[m.start("next") :]
    return text
# where the abstract ends and a publisher's block or a keyword list begins
_TAIL = re.compile(
    r"(?:(?:©|\(c\)|\ufffd)\s*(?:19|20)\d\d\b"
    r"|\bcopyright\s*(?:©\s*)?(?:19|20)\d\d\b"
    r"|\bpublished by\b"
    r"|\ball rights reserved\b"
    r"|\bthis is an open access article\b"
    r"|\bpeer[- ]review under responsibility\b"
    r"|\b(?:keywords|key words|index terms)\s*[:\u2014\u2013\-]"
    r"|©)",
    re.IGNORECASE,
)
_MIN_BODY = 40  # a "tail" this early is the text itself, not an end block


def clean_text(text: str) -> str:
    """Ligatures, non-breaking spaces, words hyphenated across a line break,
    undecodable dashes and apostrophes, runs of whitespace."""
    s = text.translate(_LIGATURES).replace("\u00a0", " ")
    s = _HYPHEN_BREAK.sub(r"\1\2", s)
    s = _BAD_APOSTROPHE.sub("\\1\u2019\\2", s)
    s = _BAD_RANGE.sub("\\1\u2013\\2", s)
    s = _BAD_DASH.sub("\\1\u2014\\2", s)
    return _WS.sub(" ", s).strip()


def clean_abstract(text: str) -> str:
    """An abstract as its authors wrote it: no label, no markup, no
    publisher block or keyword list after it."""
    s = html.unescape(_TAG.sub(" ", text or ""))
    s = s.translate(_LIGATURES).replace("\u00a0", " ")
    s = _strip_label(s.lstrip())
    s = _LEADING_JUNK.sub("", s)
    tail = next((m for m in _TAIL.finditer(s) if m.start() >= _MIN_BODY), None)
    if tail is not None:
        s = s[: tail.start()]
    s = clean_text(s)
    return s.rstrip(" ,;:\u2014\u2013-")


_PLAIN_TITLE = re.compile(r"[A-Z][a-z]+")


def in_sentence(name: str) -> str:
    """A name as it reads inside a sentence. Profiles write names in sentence
    case ("Dense retrieval with reranking"); mid-sentence that capital goes,
    unless the name is written with capitals of its own ("ResNet-50",
    "BM25") or is a single word that may be a proper name ("Python")."""
    words = re.sub(r"\([^)]*\)", " ", name).split()
    parts = [p for w in words for p in w.split("-") if p]
    if len(parts) < 2 or not _PLAIN_TITLE.fullmatch(parts[0]):
        return name
    if any(p != p.lower() for p in parts[1:] if p.isalpha()):
        return name
    return name[0].lower() + name[1:]
