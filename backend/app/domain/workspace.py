"""ResearchWorkspace domain models (Roadmap Phase 8; Data Model §7 / §13).

The persistent multi-paper container every downstream synthesis stage (RAG,
comparison, gaps, directions) reads from. Phase 8 builds only the container,
its paper collection, and the trail-review surface -- synthesis is later
phases and is not modelled here.

Tenant isolation (Data Model intro): every workspace-scoped row carries
`owner_id` and every read filters by it; a cross-tenant fetch returns
"not found", never the row.

`source_run_id` (not in the Data Model §13 column list) records the
discovery run a workspace was built from, so `GET /workspaces/{id}/trail`
can resolve the Phase 7 `paper_relationships` rows without a second join
table -- see app/db/repository.py::attach_run_edges_to_workspace.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.domain.ranking import RankedPaper

_MAX_TAGS = 50
_MAX_TAG_LEN = 64


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WorkspacePaperRole(str, Enum):
    SEED = "seed"
    RELATED = "related"


class AddedBy(str, Enum):
    TRAIL = "trail"
    MANUAL = "manual"


class Grounding(str, Enum):
    FULL_TEXT = "full_text"
    ABSTRACT = "abstract"


def _clean_tags(raw: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tag in raw:
        t = tag.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t[:_MAX_TAG_LEN])
    return out[:_MAX_TAGS]


class WorkspacePaper(BaseModel):
    workspace_id: str
    paper_id: str
    added_by: AddedBy
    role: WorkspacePaperRole = WorkspacePaperRole.RELATED
    grounding: Grounding = Grounding.ABSTRACT
    pinned: bool = False
    tags: list[str] = Field(default_factory=list)
    note: str | None = None
    order: int = 0
    ranking_snapshot: RankedPaper | None = None
    added_at: datetime = Field(default_factory=_utcnow)

    @field_validator("tags")
    @classmethod
    def _normalise_tags(cls, v: list[str]) -> list[str]:
        return _clean_tags(v)

    @field_validator("note")
    @classmethod
    def _strip_note(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class ResearchWorkspace(BaseModel):
    workspace_id: str
    owner_id: str
    title: str
    seed_paper_id: str
    seed_profile_id: str
    papers: list[WorkspacePaper] = Field(default_factory=list)
    combined_index_path: str | None = None
    source_run_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("title")
    @classmethod
    def _title_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("workspace title must not be blank")
        return v.strip()

    def paper(self, paper_id: str) -> WorkspacePaper | None:
        return next((p for p in self.papers if p.paper_id == paper_id), None)

    @property
    def related_papers(self) -> list[WorkspacePaper]:
        return [p for p in self.papers if p.role is WorkspacePaperRole.RELATED]
