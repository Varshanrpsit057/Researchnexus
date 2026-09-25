"""chat_messages: keep an answer's outcome (Phase 9 frontend chat)

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-26

Mirrors app/db/models.py (ChatMessageORM).

The RAG pipeline returns, besides the text, why an answer looks the way it
does: a suggestion when the workspace cannot answer the question, how many
sentences were dropped for lacking a supporting source, and warnings
(faithfulness below threshold, generation failed, ...). They only ever
reached the live SSE `done` event, so a reloaded conversation silently lost
them. Stored on the assistant message now; existing rows get the neutral
values (no suggestion, nothing dropped, no warnings).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.add_column(sa.Column("suggestion", sa.Text(), nullable=True))
        batch.add_column(sa.Column("unsupported_dropped", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"))


def downgrade() -> None:
    with op.batch_alter_table("chat_messages") as batch:
        batch.drop_column("warnings")
        batch.drop_column("unsupported_dropped")
        batch.drop_column("suggestion")
