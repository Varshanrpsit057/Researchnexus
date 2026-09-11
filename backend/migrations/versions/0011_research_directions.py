"""research_directions (Phase 12 -- research directions from accepted gaps)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-11

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §9 / §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 12.

Numbered 0011 (sequential) rather than the Roadmap's "0012_research_
directions" label -- the Roadmap numbering has run one ahead since Phase 5
added no migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_directions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("gap_id", sa.String(64), sa.ForeignKey("research_gaps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("proposal", sa.Text(), nullable=False, server_default=""),
        sa.Column("motivation", sa.Text(), nullable=False, server_default=""),
        sa.Column("supporting_evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("related_papers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("suggested_method", sa.Text(), nullable=False, server_default=""),
        sa.Column("possible_dataset", sa.Text(), nullable=True),
        sa.Column("evaluation_strategy", sa.Text(), nullable=False, server_default=""),
        sa.Column("risks", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("critique", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.String(16), nullable=False, server_default="low"),
        sa.Column("confidence_basis", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("flags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("user_state", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("generator_model", sa.String(255), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_directions_workspace", "research_directions", ["workspace_id"])
    op.create_index("ix_research_directions_gap_id", "research_directions", ["gap_id"])


def downgrade() -> None:
    op.drop_table("research_directions")
