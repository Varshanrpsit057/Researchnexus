"""Deterministic reference-string builder (Architecture §1.1 "Citation
string formatting ... Deterministic ... LLM never emits references";
Roadmap Phase 9). Hand-rolled CSL -> APA / IEEE / BibTeX -- no citeproc
dependency.

Input is a CSL-JSON-shaped dict (see `metadata_resolver.build_csl`). If
the title is missing the entry is treated as unresolved and every format
is the literal `"Not available"` -- a reference is never guessed.
"""

from __future__ import annotations

import re

from app.domain.citation import NOT_AVAILABLE

_STOPWORDS = {"a", "an", "the", "on", "of", "for", "and", "in", "to", "with", "from"}
_CONF_TYPES = {"paper-conference", "proceedings-article"}


def _year(csl: dict) -> int | None:
    issued = csl.get("issued")
    if isinstance(issued, int):
        return issued
    if isinstance(issued, dict):
        parts = issued.get("date-parts") or [[]]
        if parts and parts[0]:
            try:
                return int(parts[0][0])
            except (TypeError, ValueError):
                return None
    if isinstance(csl.get("year"), int):
        return int(csl["year"])
    return None


def _authors(csl: dict) -> list[tuple[str, str]]:
    """Returns [(family, given)] preserving order."""
    out: list[tuple[str, str]] = []
    for a in csl.get("author", []) or []:
        family = (a.get("family") or "").strip()
        given = (a.get("given") or "").strip()
        if family or given:
            out.append((family, given))
    return out


def _initials(given: str) -> str:
    toks = [t for t in re.split(r"\s+", given.strip()) if t]
    return " ".join(f"{t[0].upper()}." for t in toks)


def _apa_author(family: str, given: str) -> str:
    ini = _initials(given)
    return f"{family}, {ini}" if ini else family


def _apa_author_list(authors: list[tuple[str, str]]) -> str:
    parts = [_apa_author(f, g) for f, g in authors]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + ", & " + parts[-1]


def _ieee_author(family: str, given: str) -> str:
    ini = _initials(given)
    return f"{ini} {family}".strip()


def _ieee_author_list(authors: list[tuple[str, str]]) -> str:
    parts = [_ieee_author(f, g) for f, g in authors]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def _with_period(text: str) -> str:
    return text if text[-1:] in ".?!" else text + "."


def _apa(csl: dict) -> str:
    authors = _authors(csl)
    year = _year(csl)
    head = _apa_author_list(authors) if authors else (csl.get("container-title") or "")
    out = f"{head} ({year if year else 'n.d.'}). {_with_period(csl['title'])}"
    container = (csl.get("container-title") or "").strip()
    if container:
        out += f" {_with_period(container)}"
    doi = (csl.get("DOI") or "").strip()
    url = (csl.get("URL") or "").strip()
    if doi:
        out += f" https://doi.org/{doi}"
    elif url:
        out += f" {url}"
    return out


def _ieee(csl: dict, number: int | None) -> str:
    authors = _authors(csl)
    year = _year(csl)
    marker = f"[{number}] " if number is not None else ""
    head = _ieee_author_list(authors) if authors else ""
    out = f'{marker}{head}, "{csl["title"]},"' if head else f'{marker}"{csl["title"]},"'
    container = (csl.get("container-title") or "").strip()
    if container:
        out += f" in {container}"
    if year:
        out += f", {year}"
    doi = (csl.get("DOI") or "").strip()
    if doi:
        out += f", doi: {doi}"
    return out + "."


def csl_key(csl: dict) -> str:
    authors = _authors(csl)
    family = authors[0][0] if authors else "anon"
    year = _year(csl)
    title_words = re.findall(r"[a-z0-9]+", (csl.get("title") or "").lower())
    first = next((w for w in title_words if w not in _STOPWORDS), title_words[0] if title_words else "untitled")
    stem = re.sub(r"[^a-z0-9]", "", family.lower()) or "anon"
    return f"{stem}{year if year else 'nd'}{first}"


def _bibtex(csl: dict) -> str:
    ctype = csl.get("type", "")
    entrytype = "inproceedings" if ctype in _CONF_TYPES else "article" if ctype in {"article", "article-journal"} else "misc"
    fields: list[tuple[str, str]] = [("title", csl["title"])]
    authors = _authors(csl)
    if authors:
        fields.append(("author", " and ".join(f"{f}, {g}".strip(", ") for f, g in authors)))
    year = _year(csl)
    if year:
        fields.append(("year", str(year)))
    container = (csl.get("container-title") or "").strip()
    if container:
        fields.append(("booktitle" if entrytype == "inproceedings" else "journal", container))
    if csl.get("DOI"):
        fields.append(("doi", csl["DOI"].strip()))
    if csl.get("URL"):
        fields.append(("url", csl["URL"].strip()))
    body = "".join(f"  {k} = {{{v}}},\n" for k, v in fields)
    return f"@{entrytype}{{{csl_key(csl)},\n{body}}}"


def build_formatted(csl: dict, *, number: int | None = None) -> dict[str, str]:
    if not (csl.get("title") or "").strip():
        return {"apa": NOT_AVAILABLE, "ieee": NOT_AVAILABLE, "bibtex": NOT_AVAILABLE}
    return {"apa": _apa(csl), "ieee": _ieee(csl, number), "bibtex": _bibtex(csl)}
