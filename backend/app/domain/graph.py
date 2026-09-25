"""ResearchGraph domain models (Data Model §11; Roadmap Phase 13).

The per-workspace research graph: a small, JSON-persisted projection of the
workspace's own papers and its Phase 7 typed research trail -- never a
freestanding entity-extraction graph (Architecture §5: "no global knowledge
graph in the MVP"). `app/services/graph/builder.py` is the only place a
`ResearchGraph` is constructed; it may only emit nodes for papers in the
workspace or at the far end of one of its real, non-rejected `TrailEdge`s
(app/domain/trail.py), and edges that trace back to such a trail edge --
never an invented paper or relationship. Membership is carried on the node
(`in_workspace`), review state and trail provenance on the edge.

`node_count` / `edge_count` are derived, not independently settable, so a
`ResearchGraph` can never report a count that disagrees with its own
`nodes` / `edges` lists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.domain.profile import Confidence, SourceSpan
from app.domain.trail import RelationshipType, UserState
from app.domain.workspace import WorkspacePaperRole


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GraphNodeType(str, Enum):
    PAPER = "PAPER"
    METHOD = "METHOD"
    DATASET = "DATASET"
    TOPIC = "TOPIC"
    RESEARCH_QUESTION = "RESEARCH_QUESTION"
    CLAIM = "CLAIM"
    GAP = "GAP"
    DIRECTION = "DIRECTION"


class GraphEdgeType(str, Enum):
    SIMILAR = "SIMILAR"
    CITES = "CITES"
    EXTENDS = "EXTENDS"
    USES_METHOD = "USES_METHOD"
    USES_DATASET = "USES_DATASET"
    COMPETES_WITH = "COMPETES_WITH"
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    ADDRESSES = "ADDRESSES"
    EXPOSES_GAP = "EXPOSES_GAP"


class GraphNode(BaseModel):
    id: str
    type: GraphNodeType
    label: str
    paper_ids: list[str] = Field(default_factory=list)
    span: SourceSpan | None = None
    # PAPER nodes: where the paper stands relative to the workspace. A
    # connected paper (`in_workspace=False`) is the far end of one of the
    # workspace's real trail edges that was never added as a member.
    in_workspace: bool = True
    role: WorkspacePaperRole | None = None  # members only
    year: int | None = None
    authors: list[str] = Field(default_factory=list)
    venue: str | None = None


class GraphEdge(BaseModel):
    src: str
    dst: str
    type: GraphEdgeType
    evidence: list[SourceSpan] = Field(default_factory=list)
    confidence: Confidence
    # Provenance back to the trail: every trail edge folded into this graph
    # edge, their own relationship types, and their review state -- PENDING
    # while any of them still awaits review, ACCEPTED once none do.
    trail_edge_ids: list[str] = Field(default_factory=list)
    relationship_types: list[RelationshipType] = Field(default_factory=list)
    user_state: UserState = UserState.PENDING


class ResearchGraph(BaseModel):
    workspace_id: str
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    built_at: datetime = Field(default_factory=_utcnow)
    node_count: int = 0
    edge_count: int = 0

    @model_validator(mode="after")
    def _derive_counts(self) -> ResearchGraph:
        self.node_count = len(self.nodes)
        self.edge_count = len(self.edges)
        return self
