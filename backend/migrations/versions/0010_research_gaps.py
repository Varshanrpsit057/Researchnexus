"""research_gaps (Phase 11 -- structured evidence-grounded research-gap
objects)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-11

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §8 / §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 11.

Numbered 0010 (sequential) rather than the Roadmap's "0011_research_gaps"
label -- the Roadmap numbering has run one ahead since Phase 5 added no
migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_gaps",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("gap_type", sa.String(32), nullable=False),
        sa.Column("supporting_papers", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("supporting_evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("conflicting_evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("why_unaddressed", sa.Text(), nullable=False, server_default=""),
        sa.Column("affected_methods", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("affected_datasets", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("evidence_coverage", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("novelty_assessment", sa.Text(), nullable=False, server_default=""),
        sa.Column("confidence", sa.String(16), nullable=False, server_default="low"),
        sa.Column("confidence_basis", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("proposed_direction", sa.Text(), nullable=False, server_default=""),
        sa.Column("detection_rule", sa.String(48), nullable=False, server_default=""),
        sa.Column("self_support_passed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("user_state", sa.String(16), nullable=False, server_default="candidate"),
        sa.Column("generator_model", sa.String(255), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_gaps_workspace", "research_gaps", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("research_gaps")
