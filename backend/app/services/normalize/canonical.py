"""Canonicalise one `RawExternalRecord` into a `NormalizedCandidate`:
stable identity keys (title hash, versionless arXiv id, prefix-free DOI) and
tidy bibliographic fields. Deterministic, no I/O (Architecture §2: dedupe /
merge is deterministic code).

`title_hash` MUST stay byte-identical to
`app/services/ingest/pipeline.py::_title_hash` so a discovered paper dedupes
against an already-ingested one -- there is a test pinning this
(test_normalize_canonical.py::test_title_hash_matches_the_ingest_pipeline_hash).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone

from app.domain.candidate import CandidateSource, NormalizedCandidate, RawExternalRecord
from app.services.normalize.text import clean_abstract

_TITLE_HASH_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")
_ARXIV_VERSION_RE = re.compile(r"v\d+$")
_MIN_YEAR = 1900
_MAX_YEAR = datetime.now(timezone.utc).year + 1


def normalize_title(title: str) -> str:
    return " ".join(title.split()).strip()


def title_hash(title: str) -> str:
    normalized = _TITLE_HASH_NORMALIZE_RE.sub(" ", title.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    cleaned = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    cleaned = cleaned.strip()
    return cleaned if cleaned.startswith("10.") and "/" in cleaned else None


def normalize_arxiv_id(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    for prefix in ("http://arxiv.org/abs/", "https://arxiv.org/abs/", "arxiv:", "arXiv:"):
        if cleaned.lower().startswith(prefix.lower()):
            cleaned = cleaned[len(prefix) :]
    cleaned = _ARXIV_VERSION_RE.sub("", cleaned.strip())
    return cleaned or None


def normalize_authors(authors: list[str]) -> list[str]:
    seen: list[str] = []
    for a in authors:
        name = " ".join(a.split()).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def normalize_year(year: int | None) -> int | None:
    if year is None:
        return None
    return year if _MIN_YEAR <= year <= _MAX_YEAR else None


def _openalex_short_id(native_id: str | None) -> str | None:
    if not native_id:
        return None
    return native_id.rstrip("/").rsplit("/", 1)[-1] or None


def identity_keys(cand: NormalizedCandidate) -> list[str]:
    """Dedup identity keys in priority order: DOI, then versionless arXiv
    id, then normalised-title hash. Two candidates sharing any one key are
    the same paper (app/services/normalize/dedupe.py)."""
    keys: list[str] = []
    if "doi" in cand.external_ids:
        keys.append(f"doi:{cand.external_ids['doi']}")
    if "arxiv" in cand.external_ids:
        keys.append(f"arxiv:{cand.external_ids['arxiv']}")
    keys.append(f"title:{cand.title_hash}")
    return keys


def primary_identity_key(cand: NormalizedCandidate) -> str:
    return identity_keys(cand)[0]


def to_normalized(rec: RawExternalRecord) -> NormalizedCandidate:
    doi = normalize_doi(rec.doi)
    arxiv_id = normalize_arxiv_id(rec.arxiv_id)
    external_ids: dict[str, str] = {}
    if doi:
        external_ids["doi"] = doi
    if arxiv_id:
        external_ids["arxiv"] = arxiv_id
    if rec.source is CandidateSource.OPENALEX:
        short = _openalex_short_id(rec.source_native_id)
        if short:
            external_ids["openalex"] = short
    if rec.source is CandidateSource.SEMANTIC_SCHOLAR and rec.source_native_id:
        external_ids["s2"] = rec.source_native_id

    title = normalize_title(rec.title)
    return NormalizedCandidate(
        title=title,
        title_hash=title_hash(title),
        external_ids=external_ids,
        authors=normalize_authors(rec.authors),
        year=normalize_year(rec.year),
        abstract=(clean_abstract(rec.abstract or "") or None),
        venue=(rec.venue or None),
        url=(rec.url or None),
        is_preprint=rec.is_preprint,
        sources=[rec.source],
    )
