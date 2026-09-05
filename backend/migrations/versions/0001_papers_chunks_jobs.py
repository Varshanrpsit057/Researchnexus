"""papers, paper_chunks, jobs (Phase 2)

Revision ID: 0001
Revises:
Create Date: 2026-09-05

Mirrors app/db/models.py exactly. See docs/architecture/
ResearchNexus_Data_Model.md §13/§15.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "papers",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("doi", sa.String(255), unique=True, nullable=True),
        sa.Column("arxiv_id", sa.String(64), unique=True, nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("title_hash", sa.String(64), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.String(255), nullable=True),
        sa.Column("publisher", sa.String(255), nullable=True),
        sa.Column("url", sa.String(1024), nullable=True),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("has_full_text", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pdf_path", sa.String(1024), nullable=True),
        sa.Column("pdf_sha256", sa.String(64), unique=True, nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("parse_confidence", sa.String(16), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="upload"),
        sa.Column("sections", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("tables", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("references", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_papers_title_hash", "papers", ["title_hash"])
    op.create_index("ix_papers_pdf_sha256", "papers", ["pdf_sha256"])

    op.create_table(
        "paper_chunks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("paper_id", sa.String(64), sa.ForeignKey("papers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=True),
        sa.Column("section", sa.String(255), nullable=True),
        sa.Column("section_order", sa.Integer(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False, server_default="body"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding_ref", sa.String(255), nullable=True),
    )
    op.create_index("ix_paper_chunks_paper_id", "paper_chunks", ["paper_id"])
    op.create_index("ix_paper_chunks_workspace_id", "paper_chunks", ["workspace_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("owner_id", sa.String(64), nullable=False),
        sa.Column("workspace_id", sa.String(64), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("progress", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("result_ref", sa.String(64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_jobs_owner_id", "jobs", ["owner_id"])


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("paper_chunks")
    op.drop_table("papers")
