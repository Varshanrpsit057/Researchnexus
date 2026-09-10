"""ranked_papers (Phase 6)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-10

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 6.

Numbered 0005 (sequential) rather than the Roadmap's "0006_ranked_papers"
label: Phase 5 added no migration (it only writes columns that already
existed on search_candidates from 0004), so 0004 -> 0005 is the real chain.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ranked_papers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("search_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_id", sa.String(64), nullable=False),
        sa.Column("paper_id", sa.String(64), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("signals", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("weights_version", sa.String(32), nullable=False),
        sa.Column("fused_score", sa.Float(), nullable=False),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("final_rank", sa.Integer(), nullable=False),
        sa.Column("band", sa.String(16), nullable=False),
        sa.Column("explanation", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("run_id", "paper_id", name="ux_ranked_run_paper"),
    )
    op.create_index("ix_ranked_run_rank", "ranked_papers", ["run_id", "final_rank"])


def downgrade() -> None:
    op.drop_table("ranked_papers")
