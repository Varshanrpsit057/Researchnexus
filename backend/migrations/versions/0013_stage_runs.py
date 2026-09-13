"""stage_runs (Phase 14 -- orchestrator tool-call log)

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-12

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §12 / §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 14.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stage_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True),
        sa.Column("job_id", sa.String(64), nullable=True),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("tool", sa.String(64), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column("tokens_prompt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_completion", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stage_runs_owner_id", "stage_runs", ["owner_id"])
    op.create_index("ix_stage_runs_ws_stage", "stage_runs", ["workspace_id", "stage"])
    op.create_index("ix_stage_runs_ts", "stage_runs", ["ts"])


def downgrade() -> None:
    op.drop_table("stage_runs")
