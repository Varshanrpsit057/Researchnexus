"""Getting a paper's full text, and saying what text it has (remediation Phase 7).

A paper found by discovery arrived with its abstract at most. Here its full
text is looked for at the sources in sources.py, downloaded, parsed by the
same code an uploaded PDF goes through, and attached to the paper -- after
which chat, comparison and the gap engine read it, since they all read a
paper's chunks and its grounding.

What was found is kept on the paper, so a paper is never downloaded twice:
full text once retrieved stays (its PDF on disk, its chunks in the
database); "no open-access copy" is believed for a week and a failed
download for a day before an automatic run asks again. Asking explicitly
(`force`) always looks again. Nothing is invented: a paper whose full text
can't be had keeps its abstract, and says so.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.db.models import PaperORM
from app.external.allowlist import DisallowedHost
from app.external.http import (
    ExternalError,
    ExternalHttpClient,
    NotAPdf,
    TooLarge,
    UpstreamRateLimited,
    UpstreamUnavailable,
)
from app.external.keys import source_headers
from app.security.pdf_sanitizer import (
    FileTooLarge,
    PdfEncrypted,
    PdfScanned,
    PdfValidationError,
    TooManyPages,
)
from app.services.fulltext.jats import NotAnArticle, jats_document
from app.services.fulltext.sources import Candidate, find_sources
from app.services.ingest.chunker import build_chunks
from app.services.ingest.pipeline import parse_pdf
from app.services.ingest.reference_parser import parse_references
from app.telemetry.logging import get_logger

_log = get_logger(__name__)

# how long a negative answer is believed before an automatic run asks again
UNAVAILABLE_TTL = timedelta(days=7)
FAILED_TTL = timedelta(days=1)
_MAX_ATTEMPTS = 4
_HOST_SPACING_S = {"arxiv.org": 3.0, "export.arxiv.org": 3.0, "api.semanticscholar.org": 1.05, "api.openalex.org": 0.15}


@dataclass(frozen=True)
class Outcome:
    # retrieved | already | unavailable | failed | cached
    status: str
    source: str | None = None
    reason: str | None = None
    chunks: int = 0


def fulltext_http(settings: Settings) -> ExternalHttpClient:
    """One client per run: its per-host spacing keeps a batch polite (arXiv
    asks for a few seconds between requests)."""
    return ExternalHttpClient(
        timeout_s=settings.fulltext_timeout_s,
        max_retries=1,
        host_headers=source_headers(settings),
        host_min_interval_s=_HOST_SPACING_S,
        max_retry_wait_s=5.0,
    )


def _reason(exc: Exception) -> str:
    """Why one copy couldn't be used, as a code the page words."""
    if isinstance(exc, DisallowedHost):
        return "not_a_source"
    if isinstance(exc, NotAPdf):
        return "not_a_pdf"
    if isinstance(exc, (TooLarge, FileTooLarge, TooManyPages)):
        return "too_large"
    if isinstance(exc, PdfEncrypted):
        return "encrypted"
    if isinstance(exc, (PdfScanned, _NoText)):
        return "no_text_layer"
    if isinstance(exc, (PdfValidationError, NotAnArticle)):
        return "unreadable"
    if isinstance(exc, UpstreamRateLimited):
        return "rate_limited"
    if isinstance(exc, UpstreamUnavailable):
        text = str(exc)
        return f"http_{text.rsplit('HTTP ', 1)[1][:3]}" if "HTTP " in text else "unreachable"
    return "unreadable"


class _NoText(Exception):
    """The document parsed, but held no text to read (a scan)."""


def _recent(paper: PaperORM, now: datetime) -> bool:
    checked = paper.fulltext_checked_at
    if checked is None:
        return False
    if paper.fulltext_status == "unavailable":
        return now - checked < UNAVAILABLE_TTL
    if paper.fulltext_status == "failed":
        return now - checked < FAILED_TTL
    return False


async def _read(db: Session, paper: PaperORM, candidate: Candidate, http: ExternalHttpClient, settings: Settings) -> int:
    """Downloads, parses and attaches one copy; returns its chunk count."""
    if candidate.kind == "jats":
        xml = await http.get_text(candidate.url)
        text, sections = jats_document(xml)
        chunks = [
            c.model_copy(update={"page": None})  # XML has no pages; none is made up
            for c in build_chunks(paper.id, text, sections, [], [(0, len(text))], settings)
        ]
        if not chunks:
            raise _NoText(candidate.url)
        repo.attach_full_text(
            db, paper.id, pdf_path=None, sha256=None, page_count=None, parse_confidence="high",
            sections=[s.model_dump(mode="json") for s in sections], tables=[],
            references=[r.model_dump(mode="json") for r in parse_references(text, sections)],
            warnings=[], chunks=chunks, source=candidate.source, url=candidate.url,
        )
        return len(chunks)

    data, final_url = await http.get_pdf(candidate.url, max_bytes=int(settings.max_pdf_mb * 1024 * 1024))
    # parsing is CPU work and touches no database: off the event loop, so other downloads go on
    doc = await asyncio.to_thread(parse_pdf, paper.id, data, f"{paper.id}.pdf", settings)
    if not doc.document.has_text_layer or not doc.chunks:
        raise _NoText(final_url)
    path = settings.pdf_storage_dir() / f"{paper.id}.pdf"
    path.write_bytes(data)
    d = doc.document
    repo.attach_full_text(
        db, paper.id, pdf_path=str(path), sha256=doc.meta.sha256, page_count=d.page_count,
        parse_confidence=d.parse_confidence.value,
        sections=[s.model_dump(mode="json") for s in d.sections],
        tables=[t.model_dump(mode="json") for t in d.tables],
        references=[r.model_dump(mode="json") for r in d.references],
        warnings=list(d.warnings), chunks=doc.chunks, source=candidate.source, url=final_url,
    )
    return len(doc.chunks)


async def retrieve_full_text(
    db: Session,
    paper_id: str,
    settings: Settings,
    *,
    http: ExternalHttpClient | None = None,
    force: bool = False,
) -> Outcome:
    paper = repo.get_paper(db, paper_id)
    if paper is None:
        raise LookupError(paper_id)
    if paper.has_full_text:
        return Outcome("already", source=paper.fulltext_source or paper.source)
    if not force and _recent(paper, datetime.now(timezone.utc)):
        return Outcome("cached", reason=paper.fulltext_error)

    http = http or fulltext_http(settings)
    found = await find_sources(paper, http, contact_email=settings.contact_email)
    if not found.candidates:
        if found.lookup_errors and not found.elsewhere:
            reason = "lookup_failed"  # the sources couldn't be asked: that is a failure, not an answer
            repo.record_fulltext_attempt(db, paper_id, status="failed", error=reason)
            return Outcome("failed", reason=reason)
        reason = (
            f"elsewhere:{found.elsewhere[0]}" if found.elsewhere
            else "no_open_access_copy" if found.has_identifier
            else "no_identifier"
        )
        repo.record_fulltext_attempt(db, paper_id, status="unavailable", error=reason)
        return Outcome("unavailable", reason=reason)

    first: tuple[Candidate, str] | None = None
    elsewhere = list(found.elsewhere)
    for candidate in found.candidates[:_MAX_ATTEMPTS]:
        try:
            chunks = await asyncio.wait_for(_read(db, paper, candidate, http, settings), settings.fulltext_timeout_s * 2)
            return Outcome("retrieved", source=candidate.source, chunks=chunks)
        except asyncio.TimeoutError:  # not the builtin TimeoutError before Python 3.11
            first = first or (candidate, "timeout")
        except DisallowedHost as e:
            # a DOI that resolves to a site we don't download from: the copy is elsewhere, nothing failed
            if e.host and e.host not in elsewhere:
                elsewhere.append(e.host)
        except (ExternalError, PdfValidationError, NotAnArticle, _NoText) as e:
            first = first or (candidate, _reason(e))
        except Exception:  # noqa: BLE001 - a file the parser chokes on is this copy's failure; the next copy is still tried
            _log.exception("fulltext_unreadable", paper_id=paper_id, source=candidate.source)
            first = first or (candidate, "unreadable")
    if first is None:
        reason = f"elsewhere:{elsewhere[0]}" if elsewhere else "no_open_access_copy"
        repo.record_fulltext_attempt(db, paper_id, status="unavailable", error=reason)
        return Outcome("unavailable", reason=reason)
    candidate, reason = first
    repo.record_fulltext_attempt(db, paper_id, status="failed", source=candidate.source, url=candidate.url, error=reason)
    return Outcome("failed", source=candidate.source, reason=reason)


# --- what text a paper has ---------------------------------------------------------


def coverage_of(paper: PaperORM) -> dict[str, object]:
    """The text a paper is read from, for every page that shows a paper:
    full_text, abstract_only, no_text, or retrieval_failed (a copy was found
    but couldn't be read -- its abstract, if any, is used meanwhile)."""
    has_abstract = bool((paper.abstract or "").strip())
    if paper.has_full_text:
        state = "full_text"
    elif paper.fulltext_status == "failed":
        state = "retrieval_failed"
    elif has_abstract:
        state = "abstract_only"
    else:
        state = "no_text"
    checked = paper.fulltext_checked_at
    return {
        "state": state,
        "source": paper.fulltext_source if paper.fulltext_status == "retrieved" else ("upload" if paper.has_full_text else None),
        "status": paper.fulltext_status,  # null: its full text was never looked for
        "reason": paper.fulltext_error,
        "checked_at": checked.isoformat() if checked else None,
        "has_abstract": has_abstract,
        # an uploaded PDF that couldn't be read is re-uploaded, not retrieved
        "retrievable": not paper.has_full_text and paper.source != "upload",
    }
