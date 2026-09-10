"""workspaces + workspace_papers (Phase 8 -- the research workspace)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-10

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §7 / §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 8.

Numbered 0007 (sequential) rather than the Roadmap's "0008_workspaces"
label -- the Roadmap numbering has been one ahead since Phase 5 added no
migration.

Also adds `ix_paper_relationships_workspace`: the Phase 7 trail rows carry
a nullable `workspace_id` (created in 0006); Phase 8 stamps it when a
workspace imports a discovery run, and `GET /workspaces/{id}/trail`
filters on it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("seed_paper_id", sa.String(64), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("seed_profile_id", sa.String(64), nullable=False),
        sa.Column(
            "source_run_id",
            sa.String(64),
            sa.ForeignKey("search_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("combined_index_path", sa.String(1024), nullable=True),
        sa.Column("token_budget_usd", sa.Float(), nullable=False, server_default="5.0"),
        sa.Column("tokens_prompt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_completion", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspaces_owner", "workspaces", ["owner_id"])

    op.create_table(
        "workspace_papers",
        sa.Column(
            "workspace_id",
            sa.String(64),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("paper_id", sa.String(64), sa.ForeignKey("papers.id"), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("added_by", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("role", sa.String(16), nullable=False, server_default="related"),
        sa.Column("grounding", sa.String(16), nullable=False, server_default="abstract"),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ranking_snapshot", sa.JSON(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_wp_owner", "workspace_papers", ["owner_id"])

    op.create_index("ix_paper_relationships_workspace", "paper_relationships", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_paper_relationships_workspace", table_name="paper_relationships")
    op.drop_index("ix_wp_owner", table_name="workspace_papers")
    op.drop_table("workspace_papers")
    op.drop_index("ix_workspaces_owner", table_name="workspaces")
    op.drop_table("workspaces")
