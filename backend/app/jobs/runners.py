"""Which server process runs which job, so a job cut off by its process
stopping is reported as failed -- by any server, and without touching jobs
another live server is still running.

Jobs run inside the process that accepted them (FastAPI background tasks).
Each process registers itself in `job_runners` at start and refreshes its
heartbeat every HEARTBEAT_S; every job it creates carries its id. Every
heartbeat, a process also looks for queued/running jobs whose process
hasn't been heard from for DEAD_AFTER_S (or that predate runner ids) and
marks them failed. A process shutting down cleanly marks its own
unfinished jobs failed and removes itself.

With one server this behaves like the old start-up sweep; with several
(a rolling deploy, or more than one container) a starting server no longer
fails the jobs of one still running.
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import JobORM, JobRunnerORM
from app.domain.jobs import JobStatus
from app.telemetry.logging import get_logger

_log = get_logger(__name__)

HEARTBEAT_S = 30.0
DEAD_AFTER_S = 120.0
INTERRUPTED = "The server restarted before this finished."

RUNNER_ID = f"{socket.gethostname()[:40]}:{os.getpid()}:{secrets.token_hex(4)}"
_ACTIVE = (JobStatus.QUEUED.value, JobStatus.RUNNING.value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def register(db: Session) -> None:
    now = _now()
    row = db.get(JobRunnerORM, RUNNER_ID)
    if row is None:
        db.add(JobRunnerORM(id=RUNNER_ID, started_at=now, heartbeat_at=now))
    else:
        row.heartbeat_at = now
    db.commit()


def _fail(rows: list[JobORM]) -> None:
    for row in rows:
        row.status = JobStatus.FAILED.value
        row.error = INTERRUPTED
        row.progress = {**(row.progress or {}), "stage": "interrupted"}


def sweep(db: Session) -> int:
    """Fail the active jobs whose process is gone; forget dead processes."""
    cutoff = _now() - timedelta(seconds=DEAD_AFTER_S)
    alive = select(JobRunnerORM.id).where(JobRunnerORM.heartbeat_at >= cutoff)
    rows = list(
        db.execute(
            select(JobORM).where(
                JobORM.status.in_(_ACTIVE),
                or_(JobORM.runner_id.is_(None), JobORM.runner_id.not_in(alive)),
            )
        )
        .scalars()
        .all()
    )
    _fail(rows)
    db.execute(delete(JobRunnerORM).where(JobRunnerORM.heartbeat_at < cutoff - timedelta(days=1)))
    db.commit()
    return len(rows)


def release(db: Session) -> int:
    """At a clean shutdown: this process's unfinished jobs end as failed."""
    rows = list(db.execute(select(JobORM).where(JobORM.status.in_(_ACTIVE), JobORM.runner_id == RUNNER_ID)).scalars().all())
    _fail(rows)
    db.execute(delete(JobRunnerORM).where(JobRunnerORM.id == RUNNER_ID))
    db.commit()
    return len(rows)


class Heartbeat:
    """Registers this process, then beats (and sweeps) in a daemon thread."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._factory = session_factory
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="job-runner-heartbeat", daemon=True)

    def _tick(self) -> None:
        db = self._factory()
        try:
            register(db)
            failed = sweep(db)
            if failed:
                _log.info("interrupted_jobs_failed", count=failed)
        except Exception:  # noqa: BLE001 - a missed beat is retried; the database may be briefly away
            db.rollback()
            _log.warning("job_heartbeat_failed", exc_info=True)
        finally:
            db.close()

    def _run(self) -> None:
        while not self._stop.wait(HEARTBEAT_S):
            self._tick()

    def start(self) -> None:
        self._tick()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        db = self._factory()
        try:
            released = release(db)
            if released:
                _log.info("unfinished_jobs_released", count=released)
        except Exception:  # noqa: BLE001 - shutting down; the next sweep catches them
            db.rollback()
        finally:
            db.close()
