"""search_runs, search_candidates (Phase 4)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-09

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 4.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("workspace_id", sa.String(64), nullable=True),
        sa.Column("seed_paper_id", sa.String(64), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("strategies_requested", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("strategies_succeeded", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("strategies_failed", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("filters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("extra_citation_hop_used", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("counts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("tokens_prompt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_completion", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_search_runs_owner", "search_runs", ["owner_id"])

    op.create_table(
        "search_candidates",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("search_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paper_id", sa.String(64), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("discovery_methods", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("citation_relationship", sa.String(32), nullable=False, server_default="none"),
        sa.Column("citation_hops", sa.Integer(), nullable=True),
        sa.Column("raw_signals", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("preliminary_rank", sa.Integer(), nullable=True),
        sa.Column("possible_duplicate_of", sa.String(64), nullable=True),
        sa.Column("filter_kept", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("filter_reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("provenance", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("run_id", "paper_id", name="ux_search_candidates_run_paper"),
    )
    op.create_index("ix_search_candidates_run", "search_candidates", ["run_id"])


def downgrade() -> None:
    op.drop_table("search_candidates")
    op.drop_table("search_runs")
