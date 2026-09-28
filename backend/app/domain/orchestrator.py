"""ResearchOrchestrator domain models (Data Model §13 `stage_runs`;
Architecture §4; Roadmap Phase 14).

`StageName` is the fixed set of stages the orchestrator knows how to run
(`app/services/orchestrator/tools.py` fixes their order into a DAG with no
runtime node creation). `StageRun` is the append-only observability record
every stage call writes -- Data Model §13's invariant is explicit: **no
prompt/response bodies, no secrets**, only hashes, counts, and a short
error string.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StageName(str, Enum):
    INGEST = "ingest"
    PROFILE = "profile"
    DISCOVERY = "discovery"
    RANKING = "ranking"
    TRAIL = "trail"
    WORKSPACE = "workspace"
    RAG = "rag"
    COMPARISON = "comparison"
    GAPS = "gaps"
    DIRECTIONS = "directions"
    CITATIONS = "citations"


class StageRun(BaseModel):
    id: str
    owner_id: str
    workspace_id: str | None = None
    job_id: str | None = None
    stage: StageName
    tool: str
    input_hash: str
    output_hash: str
    tokens_prompt: int = 0
    tokens_completion: int = 0
    latency_ms: int
    ok: bool
    error: str | None = None
    ts: datetime = Field(default_factory=_utcnow)
