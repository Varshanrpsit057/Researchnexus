"""Identifiers printed in a PDF (remediation, 2026-10-02): the DOI a
publisher stamps on a paper -- in its header, its footer, or sideways in the
margin, where IEEE puts it (and where text extraction can return it with its
characters in reverse order).

Deterministic and conservative: a DOI is only ever read from the paper's own
text, never guessed; the first page's is preferred, as later pages cite other
papers' DOIs in their references.
"""

from __future__ import annotations

import re

# Crossref's recommended pattern for modern DOIs, closed at whitespace and at
# characters that end a DOI in running text
_DOI = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+[A-Za-z0-9])")


def _clean(doi: str) -> str:
    return doi.rstrip(".,;:)").lower()


def find_doi(first_page: str, margin: str = "") -> str | None:
    """The paper's own DOI, from its first page or its margin stamp."""
    for text in (margin, margin[::-1], first_page):
        m = _DOI.search(text)
        if m:
            return _clean(m.group(1))
    return None
