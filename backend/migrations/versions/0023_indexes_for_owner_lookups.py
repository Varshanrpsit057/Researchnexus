"""Indexes for the reader's library and a workspace's latest job

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-09

Mirrors app/db/models.py (ResearchProfileORM.owner_id index=True,
JobORM ix_jobs_workspace_kind).

The library (`GET /api/v1/papers`) looks up the profiles a reader produced
by `research_profiles.owner_id`, and every workspace page asks for its
latest job of a kind by `jobs (workspace_id, kind)`; both scanned the whole
table. Indexes only: no data changes, and each is skipped when present.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table) if i["name"]}


def upgrade() -> None:
    if "ix_research_profiles_owner_id" not in _indexes("research_profiles"):
        op.create_index("ix_research_profiles_owner_id", "research_profiles", ["owner_id"])
    if "ix_jobs_workspace_kind" not in _indexes("jobs"):
        op.create_index("ix_jobs_workspace_kind", "jobs", ["workspace_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_jobs_workspace_kind", table_name="jobs")
    op.drop_index("ix_research_profiles_owner_id", table_name="research_profiles")
