"""papers.fulltext_*: what came of looking for a paper's full text

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-30

Mirrors app/db/models.py (PaperORM.fulltext_*), remediation Phase 7.

A paper found by discovery had only its abstract, and nothing recorded
whether its full text had been looked for, found, or failed to download --
so it could neither be retried nor told apart from a paper with no text at
all. `fulltext_status` is null (never looked for), "retrieved", "unavailable"
(no open-access copy from a source ResearchNexus retrieves from) or "failed"
(a copy was found but couldn't be downloaded or read); the other columns say
where it came from, why it failed, and when it was last checked. All
nullable: existing rows are simply "never looked for".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("papers") as batch:
        batch.add_column(sa.Column("fulltext_status", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("fulltext_source", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("fulltext_url", sa.String(length=1024), nullable=True))
        batch.add_column(sa.Column("fulltext_error", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("fulltext_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("papers") as batch:
        batch.drop_column("fulltext_checked_at")
        batch.drop_column("fulltext_error")
        batch.drop_column("fulltext_url")
        batch.drop_column("fulltext_source")
        batch.drop_column("fulltext_status")
