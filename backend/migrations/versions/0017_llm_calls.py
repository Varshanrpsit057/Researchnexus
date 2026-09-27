"""llm_calls: every model-provider call with the provider's own token usage

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-27

Mirrors app/db/models.py (LlmCallORM).

Token usage was summed per chat answer only, so a failed turn, and every
call gaps, directions, comparison, profiling and discovery made, left no
record at all, and the workspace budget always read $0. One row per call
(answered or failed) is what a real usage figure can be built from.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cached_prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reasoning_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_kind", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_calls_owner_created", "llm_calls", ["owner_id", "created_at"])
    op.create_index("ix_llm_calls_workspace", "llm_calls", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_llm_calls_workspace", table_name="llm_calls")
    op.drop_index("ix_llm_calls_owner_created", table_name="llm_calls")
    op.drop_table("llm_calls")
