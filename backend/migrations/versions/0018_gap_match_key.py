"""research_gaps.match_key: remember a gap decision by what the gap says

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-27

Mirrors app/db/models.py (ResearchGapORM.match_key).

`gap_id` hashes the gap's supporting-paper set, and a gap run profiles more
of a workspace's papers each time -- so the same gap, found again with one
more paper, got a new id: a rejected gap came back as a new candidate and an
accepted one got a near-duplicate. `match_key` is the gap without its paper
set (type, rule, the rule's key facts); decisions are matched on it too.
Nullable: rows from before this revision keep matching by id only.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("research_gaps") as batch:
        batch.add_column(sa.Column("match_key", sa.String(length=64), nullable=True))
        batch.create_index("ix_research_gaps_workspace_match", ["workspace_id", "match_key"])


def downgrade() -> None:
    with op.batch_alter_table("research_gaps") as batch:
        batch.drop_index("ix_research_gaps_workspace_match")
        batch.drop_column("match_key")
