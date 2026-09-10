"""paper_relationships (Phase 7 -- the typed research trail)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-10

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 7.

Numbered 0006 (sequential) rather than the Roadmap's "0007_paper_relationships"
label. The pre-workspace MVP scopes the trail to a `run_id`
(FK -> search_runs, CASCADE); `workspace_id` / `owner_id` are nullable and
get FKs + population in Phase 8.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paper_relationships",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("search_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=True),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("source_paper_id", sa.String(64), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("target_paper_id", sa.String(64), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("relationship_type", sa.String(32), nullable=False),
        sa.Column("detection_method", sa.String(32), nullable=False),
        sa.Column("rule_fired", sa.Text(), nullable=True),
        sa.Column("llm_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("supporting_references", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("confidence_basis", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("user_state", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "run_id", "source_paper_id", "target_paper_id", "relationship_type",
            name="ux_paper_rel_run_src_tgt_type",
        ),
    )
    op.create_index("ix_paper_relationships_run", "paper_relationships", ["run_id"])


def downgrade() -> None:
    op.drop_table("paper_relationships")
