"""search_runs.report: how a discovery run went

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-01

Mirrors app/db/models.py (SearchRunORM.report), remediation Phase 8.

A run kept only which strategies succeeded or failed, so a "partial" run --
9 of the 15 real discover jobs so far -- could not say what was missing or
why: that citation search ran out of time after finding 40 papers, or that
OpenAlex had paused anonymous search. `report` holds the run's own record
of each step (state, seconds), strategy (state, papers found, notes) and
source (answers, failures, the last failure). Nullable: runs saved before
this have no report, and say so.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("search_runs") as batch:
        batch.add_column(sa.Column("report", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("search_runs") as batch:
        batch.drop_column("report")
