"""Who published a paper, named the way readers know them (remediation,
2026-10-02).

A publisher comes from the sources' own metadata (Crossref's `publisher`,
OpenAlex's host organisation) and, when they name none, from the DOI's
prefix -- each prefix is registered to one publisher, so this is a lookup,
not a guess. Names are normalised so "Institute of Electrical and
Electronics Engineers (IEEE)" and "IEEE" are one publisher, and a ranking or
a filter can tell the publishers a person trusts from the rest.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

# the publishers discovery can rank first (the user's choice, 2026-10-02)
TRUSTED_PUBLISHERS = ("IEEE", "Springer", "ACM", "Elsevier")

# DOI prefix -> publisher (Crossref's registrants for these prefixes)
_PREFIX = {
    "10.1109": "IEEE",
    "10.1007": "Springer",
    "10.1038": "Springer",  # Springer Nature
    "10.1186": "Springer",  # BioMed Central, Springer Nature
    "10.1140": "Springer",  # EPJ
    "10.1145": "ACM",
    "10.1016": "Elsevier",
    "10.2139": "Elsevier",  # SSRN
    "10.3390": "MDPI",
    "10.1002": "Wiley",
    "10.1111": "Wiley",
    "10.1155": "Wiley",  # Hindawi
    "10.1049": "IET",
    "10.1080": "Taylor & Francis",
    "10.1201": "Taylor & Francis",  # CRC Press
    "10.1177": "SAGE",
    "10.1093": "Oxford University Press",
    "10.1017": "Cambridge University Press",
    "10.1371": "PLOS",
    "10.3389": "Frontiers",
    "10.1088": "IOP Publishing",
    "10.1063": "AIP Publishing",
    "10.1103": "American Physical Society",
    "10.1021": "American Chemical Society",
    "10.1039": "Royal Society of Chemistry",
    "10.1126": "AAAS",
    "10.1073": "PNAS",
    "10.1162": "MIT Press",
    "10.18653": "ACL",
    "10.1117": "SPIE",
    "10.7717": "PeerJ",
    "10.48550": "arXiv",
    "10.1101": "Cold Spring Harbor Laboratory",  # bioRxiv / medRxiv
}

# substrings of the names sources use -> the name readers use
_NAMES = (
    ("institute of electrical and electronics engineers", "IEEE"),
    ("ieee", "IEEE"),
    ("springer", "Springer"),
    ("nature portfolio", "Springer"),
    ("biomed central", "Springer"),
    ("association for computing machinery", "ACM"),
    ("elsevier", "Elsevier"),
    ("mdpi", "MDPI"),
    ("multidisciplinary digital publishing", "MDPI"),
    ("wiley", "Wiley"),
    ("hindawi", "Wiley"),
    ("taylor & francis", "Taylor & Francis"),
    ("taylor and francis", "Taylor & Francis"),
    ("informa uk", "Taylor & Francis"),
    ("sage publications", "SAGE"),
    ("oxford university press", "Oxford University Press"),
    ("cambridge university press", "Cambridge University Press"),
    ("public library of science", "PLOS"),
    ("frontiers media", "Frontiers"),
    ("institution of engineering and technology", "IET"),
    ("iop publishing", "IOP Publishing"),
    ("association for computational linguistics", "ACL"),
)
_LEGAL_SUFFIX = re.compile(r"[\s,]+(?:bv|b\.v\.|llc|ltd|inc\.?|gmbh|ag|s\.a\.|co\.)$", re.IGNORECASE)


def from_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/").removeprefix("doi:")
    return _PREFIX.get(d.split("/", 1)[0])


def normalize(name: str | None) -> str | None:
    """A source's publisher name, as readers know it."""
    if not name or not name.strip():
        return None
    low = " ".join(name.lower().split())
    if low == "acm":
        return "ACM"
    for needle, canonical in _NAMES:
        if needle in low:
            return canonical
    return _LEGAL_SUFFIX.sub("", " ".join(name.split())).strip() or None


def publisher_of(name: str | None, doi: str | None) -> str | None:
    """The publisher a source names, else the one the DOI is registered to."""
    return normalize(name) or from_doi(doi)


def is_trusted(publisher: str | None) -> bool:
    return publisher in TRUSTED_PUBLISHERS


def preferred_set(names: Iterable[str] | None) -> tuple[str, ...]:
    """The publishers a reader prefers, named as readers know them, once each
    and in their order; None is the default four (remediation, 2026-10-06:
    the reader chooses them in Settings)."""
    if names is None:
        return TRUSTED_PUBLISHERS
    out: list[str] = []
    for name in names:
        canonical = normalize(name)
        if canonical and canonical not in out:
            out.append(canonical)
    return tuple(out)


def known_publishers() -> list[str]:
    """Every publisher this module can name, for choosing preferred ones."""
    return sorted({*_PREFIX.values(), *(c for _, c in _NAMES)}, key=str.lower)
