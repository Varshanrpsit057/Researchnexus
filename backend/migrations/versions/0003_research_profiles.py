"""research_profiles (Phase 3)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-06

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 3.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_profiles",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("paper_id", sa.String(64), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("grounding", sa.String(16), nullable=False, server_default="full_text"),
        sa.Column("profile_json", sa.JSON(), nullable=False),
        sa.Column("extraction_confidence", sa.String(16), nullable=False, server_default="low"),
        sa.Column("extraction_model", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("paper_id", "workspace_id", name="ux_research_profiles_paper_workspace"),
    )
    op.create_index("ix_profiles_paper", "research_profiles", ["paper_id"])
    op.create_index("ix_profiles_workspace", "research_profiles", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("research_profiles")
