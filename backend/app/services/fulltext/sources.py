"""Where a paper's full text can legitimately be read from (remediation Phase 7).

Only the sources ResearchNexus already searches, asked by the paper's own
identifiers -- never a title guess, which could fetch another paper:

- arXiv, by its arXiv id (or an arXiv DOI): the preprint PDF;
- OpenAlex, by DOI: the open-access locations it lists for the work, and
  its PubMed Central id;
- Europe PMC, by that PMC id: the article's full-text XML;
- Semantic Scholar, by DOI: its `openAccessPdf`, asked only when the others
  found nothing ResearchNexus can read.

A copy is kept only when its host is on the full-text source list
(app/external/allowlist.py); an open-access copy elsewhere is reported, not
fetched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from app.db.models import PaperORM
from app.external.allowlist import fulltext_host_allowed
from app.external.core_client import CoreClient, download_url
from app.external.http import ExternalError, ExternalHttpClient
from app.external.openalex_client import OpenAlexClient
from app.external.semantic_scholar_client import SemanticScholarClient
from app.services.metadata.lookup import same_title

_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)
_ARXIV_ABS = re.compile(r"arxiv\.org/(?:abs|pdf)/([^?#]+?)(?:\.pdf)?$", re.IGNORECASE)
_PMCID = re.compile(r"(PMC\d+)", re.IGNORECASE)
_EUROPE_PMC_XML = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


@dataclass(frozen=True)
class Candidate:
    source: str  # arxiv | europepmc | unpaywall | openalex | core | semantic_scholar
    url: str
    kind: str = "pdf"  # "pdf", or "jats" for Europe PMC's full-text XML


@dataclass
class Found:
    candidates: list[Candidate] = field(default_factory=list)
    # hosts holding an open-access copy that isn't on the full-text source list
    elsewhere: list[str] = field(default_factory=list)
    # a source that couldn't be asked (the others still were)
    lookup_errors: list[str] = field(default_factory=list)
    # an extra source (Unpaywall, CORE) that couldn't be asked: what the main
    # sources answered still stands
    extra_errors: list[str] = field(default_factory=list)
    has_identifier: bool = False


def arxiv_pdf(arxiv_id: str) -> str:
    return f"https://arxiv.org/pdf/{arxiv_id.strip()}"


def _add(found: Found, candidate: Candidate) -> None:
    if any(c.url == candidate.url for c in found.candidates):
        return
    if fulltext_host_allowed(candidate.url):
        found.candidates.append(candidate)
    else:
        host = (urlparse(candidate.url).hostname or "").lower()
        if host and host not in found.elsewhere:
            found.elsewhere.append(host)


def _from_openalex(found: Found, work: dict[str, Any]) -> str | None:
    """Adds the work's open-access PDF locations; returns its PMC id, if any."""
    locations = [work.get("best_oa_location"), *(work.get("locations") or [])]
    for loc in locations:
        if not isinstance(loc, dict) or not loc.get("is_oa"):
            continue  # a closed location is not a legitimate source, whatever link it has
        landing = str(loc.get("landing_page_url") or "")
        if m := _ARXIV_ABS.search(landing):
            _add(found, Candidate("arxiv", arxiv_pdf(m.group(1))))
        if pdf := loc.get("pdf_url"):
            _add(found, Candidate("openalex", str(pdf)))
    pmcid = (work.get("ids") or {}).get("pmcid")
    m = _PMCID.search(str(pmcid or ""))
    return m.group(1).upper() if m else None


async def _from_unpaywall(found: Found, http: ExternalHttpClient, doi: str, email: str) -> None:
    """Unpaywall's open-access copies of a DOI (remediation, 2026-10-02): it
    tracks where each article is legally free -- publishers' OA pages,
    university repositories, preprint servers. Its API requires an email."""
    resp = await http.get_response(f"https://api.unpaywall.org/v2/{doi}", params={"email": email})
    if resp.status_code != 200:
        return
    try:
        body = resp.json()
    except ValueError:
        return
    for loc in [body.get("best_oa_location"), *(body.get("oa_locations") or [])]:
        if isinstance(loc, dict) and (pdf := loc.get("url_for_pdf")):
            _add(found, Candidate("unpaywall", str(pdf)))


async def _from_core(found: Found, http: ExternalHttpClient, doi: str | None, title: str) -> None:
    """CORE's repository copy of the paper, matched by DOI or exact title."""
    core = CoreClient(http)
    records = await core.by_doi(doi) if doi else await core.by_title(title)
    for record in records:
        same = (doi and (record.doi or "").lower() == doi) or same_title(record.title, title)
        if same and (url := download_url(record)):
            _add(found, Candidate("core", url))


async def find_sources(paper: PaperORM, http: ExternalHttpClient, *, contact_email: str | None = None) -> Found:
    found = Found()
    doi = (paper.doi or "").strip().lower() or None
    arxiv = paper.arxiv_id or (m.group(1) if doi and (m := _ARXIV_DOI.match(doi)) else None)
    found.has_identifier = bool(doi or arxiv)
    if arxiv:
        _add(found, Candidate("arxiv", arxiv_pdf(arxiv)))

    pmcid: str | None = None
    if doi:
        try:
            work = await OpenAlexClient(http).get_work(doi)
            if work:
                pmcid = _from_openalex(found, work)
        except ExternalError as e:
            found.lookup_errors.append(f"openalex: {e}")
        if not found.candidates and not pmcid:
            try:
                s2 = await SemanticScholarClient(http).open_access(f"DOI:{doi}")
                if s2:
                    ids = s2.get("externalIds") or {}
                    if ids.get("ArXiv"):
                        _add(found, Candidate("arxiv", arxiv_pdf(str(ids["ArXiv"]))))
                    if ids.get("PubMedCentral"):
                        pmcid = f"PMC{str(ids['PubMedCentral']).upper().removeprefix('PMC')}"
                    if url := (s2.get("openAccessPdf") or {}).get("url"):
                        _add(found, Candidate("semantic_scholar", str(url)))
            except ExternalError as e:
                found.lookup_errors.append(f"semantic_scholar: {e}")
    if pmcid:
        _add(found, Candidate("europepmc", _EUROPE_PMC_XML.format(pmcid=pmcid), kind="jats"))

    # where else the article is legally free: Unpaywall (by DOI), then CORE's repositories
    if doi and contact_email:
        try:
            await _from_unpaywall(found, http, doi, contact_email)
        except ExternalError as e:
            found.extra_errors.append(f"unpaywall: {e}")
    if not found.candidates and (doi or paper.title):
        try:
            await _from_core(found, http, doi, paper.title or "")
        except ExternalError as e:
            found.extra_errors.append(f"core: {e}")

    # the most dependable first: arXiv and PubMed Central serve exactly the article
    rank = {"arxiv": 0, "europepmc": 1, "unpaywall": 2, "openalex": 3, "core": 4, "semantic_scholar": 5}
    found.candidates.sort(key=lambda c: rank[c.source])
    return found
