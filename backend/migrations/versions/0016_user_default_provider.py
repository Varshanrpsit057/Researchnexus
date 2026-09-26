"""users.default_provider: the provider every LLM stage uses (Phase 14 settings)

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-26

Mirrors app/db/models.py (UserORM).

API spec §2 has `GET /me` return `default_provider`, but nothing stored one:
it was always null, and with several working keys each stage silently took
"the first working key" in unspecified row order. Nullable: existing users
keep the old behaviour (first working key, now in the order saved) until
they choose.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("default_provider", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("default_provider")
