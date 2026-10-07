"""Full text for a workspace's papers, several at a time (remediation Phase 7).

Run in the background when papers join a workspace, and on request. A few
papers are read at once; each source still spaces its own requests. One
paper's failure is its own -- it is recorded on that paper, and the rest go on.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import Settings
from app.db import repository as repo
from app.domain.workspace import ResearchWorkspace
from app.services.fulltext.retrieve import Outcome, fulltext_http, retrieve_full_text
from app.telemetry.logging import get_logger

_log = get_logger(__name__)

Progress = Callable[[dict[str, str]], None]


def papers_to_read(db: Session, workspace: ResearchWorkspace) -> list[str]:
    """Members without full text that retrieval could give it to: a paper
    found by discovery. An uploaded PDF that couldn't be read is uploaded
    again, not looked for."""
    out: list[str] = []
    for wp in workspace.papers:
        paper = repo.get_paper(db, wp.paper_id)
        if paper is not None and not paper.has_full_text and paper.source != "upload":
            out.append(wp.paper_id)
    return out


async def retrieve_many(
    db: Session,
    paper_ids: list[str],
    settings: Settings,
    *,
    force: bool = False,
    on_progress: Progress | None = None,
) -> Counter[str]:
    """Each paper's outcome, counted: retrieved / unavailable / failed /
    cached (a recent negative answer, not asked again) / already."""
    http = fulltext_http(settings)
    counts: Counter[str] = Counter()
    done = 0
    limit = asyncio.Semaphore(max(1, settings.fulltext_concurrency))
    report = on_progress or (lambda _step: None)
    report({"stage": "retrieving", "done": "0", "total": str(len(paper_ids))})

    async def one(pid: str) -> None:
        nonlocal done
        async with limit:
            try:
                outcome = await retrieve_full_text(db, pid, settings, http=http, force=force)
            except Exception:  # noqa: BLE001 - one paper's failure is its own; the rest go on
                _log.exception("fulltext_failed", paper_id=pid)
                repo.record_fulltext_attempt(db, pid, status="failed", error="internal")
                outcome = Outcome("failed", reason="internal")
        counts[outcome.status] += 1
        done += 1
        report({"stage": "retrieving", "done": str(done), "total": str(len(paper_ids)), "retrieved": str(counts["retrieved"])})

    await asyncio.gather(*(one(pid) for pid in paper_ids))
    return counts
