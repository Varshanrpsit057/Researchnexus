"""users, api_keys (Phase 1)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-05

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 1.

This project's actual build order implemented Phase 2 (PDF ingestion)
before Phase 1 (auth/BYOK), so this migration is 0002 rather than 0001
despite Phase 1 being roadmap-numbered first -- 0001 (papers/paper_chunks/
jobs) already shipped and is never renumbered.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("auth_provider", sa.String(32), nullable=False, server_default="local"),
        sa.Column("auth_subject", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email", name="ux_users_email"),
        sa.UniqueConstraint("auth_provider", "auth_subject", name="ux_users_auth_identity"),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("key_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_last4", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="unverified"),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "provider", name="ux_api_keys_owner_provider"),
    )
    op.create_index("ix_api_keys_owner", "api_keys", ["owner_id"])


def downgrade() -> None:
    op.drop_table("api_keys")
    op.drop_table("users")
