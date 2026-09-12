"""workspaces.graph_json (Phase 13 -- per-workspace research graph)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-12

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §11 / §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 13 (there labelled
"0013_workspace_graph_json"; numbered 0012 here, sequential with the
already-applied migrations).

No new table: the ResearchGraph is JSON-persisted directly on the workspace
row, same pattern as Phase 10's `workspaces.comparison_schema` (0009).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("graph_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspaces", "graph_json")
