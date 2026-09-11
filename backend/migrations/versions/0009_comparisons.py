"""comparisons + workspaces.comparison_schema (Phase 10 -- multi-paper
comparison)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-11

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §7 / §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 10.

Numbered 0009 (sequential); the Roadmap has no separate migration label for
Phase 10.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("comparison_schema", sa.JSON(), nullable=True))

    op.create_table(
        "comparisons",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("schema_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("paper_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("rows_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("coverage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("decontext_eval", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_comparisons_workspace", "comparisons", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("comparisons")
    op.drop_column("workspaces", "comparison_schema")
