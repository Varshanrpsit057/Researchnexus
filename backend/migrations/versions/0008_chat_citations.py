"""chat_sessions + chat_messages + citations + claims (Phase 9 -- RAG +
citation/evidence system)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-11

Mirrors app/db/models.py. See docs/architecture/
ResearchNexus_Data_Model.md §10 / §13; docs/architecture/
ResearchNexus_Implementation_Roadmap.md Phase 9.

Numbered 0008 (sequential) rather than the Roadmap's "0009_chat_claims"
label -- the Roadmap numbering has been one ahead since Phase 5 added no
migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_sessions_workspace", "chat_sessions", ["workspace_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("citations", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("tokens_prompt", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_completion", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("faithfulness", sa.Float(), nullable=True),
        sa.Column("answerable", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_messages_session", "chat_messages", ["session_id"])
    op.create_index("ix_msg_session", "chat_messages", ["session_id", "created_at"])

    op.create_table(
        "citations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", sa.String(64), nullable=True),
        sa.Column("paper_id", sa.String(64), sa.ForeignKey("papers.id"), nullable=False),
        sa.Column("csl_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("formatted", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("resolved_from", sa.String(16), nullable=False, server_default="unresolved"),
        sa.UniqueConstraint("workspace_id", "paper_id", name="ux_citations_workspace_paper"),
    )
    op.create_index("ix_citations_workspace", "citations", ["workspace_id"])

    op.create_table(
        "claims",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("workspace_id", sa.String(64), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("artefact_kind", sa.String(24), nullable=False),
        sa.Column("artefact_id", sa.String(64), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("supporting_chunk_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("supporting_paper_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("is_supported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("citation_precision", sa.Float(), nullable=True),
        sa.Column("citation_recall", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_claims_workspace", "claims", ["workspace_id"])
    op.create_index("ix_claims_artefact", "claims", ["artefact_id"])


def downgrade() -> None:
    op.drop_table("claims")
    op.drop_table("citations")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_workspace", table_name="chat_sessions")
    op.drop_table("chat_sessions")
