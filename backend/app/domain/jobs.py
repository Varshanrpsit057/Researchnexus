"""Async job domain model.

Mirrors docs/architecture/ResearchNexus_Data_Model.md §12. Phase 2 uses this
only for `JobKind.INGEST` (PDF validate -> parse -> chunk), run via FastAPI
BackgroundTasks per docs/architecture/ResearchNexus_Implementation_
Architecture.md §7 ("FastAPI BackgroundTasks (MVP)"). `PIPELINE` (Roadmap
Phase 14) tracks a `ResearchOrchestrator.run_full_pipeline` call end to
end; its own `progress` dict names the current stage (e.g.
`{"stage": "discovery"}`), same shape as the Data Model's own
`{"semantic": "done", "citation": "running", ...}` example.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class JobKind(str, Enum):
    INGEST = "ingest"
    PROFILE = "profile"
    DISCOVER = "discover"
    RANK = "rank"
    TRAIL = "trail"
    GAPS = "gaps"
    DIRECTIONS = "directions"
    INDEX_REBUILD = "index_rebuild"
    PIPELINE = "pipeline"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(BaseModel):
    job_id: str
    owner_id: str
    workspace_id: str | None = None
    kind: JobKind
    status: JobStatus = JobStatus.QUEUED
    progress: dict[str, str] = Field(default_factory=dict)
    result_ref: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
