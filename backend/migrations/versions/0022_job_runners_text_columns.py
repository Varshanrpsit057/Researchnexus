"""Job runners; free-text columns as TEXT

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-09

Mirrors app/db/models.py (JobORM.runner_id, JobRunnerORM, and the columns
below as Text).

1. jobs.runner_id + job_runners: which server process runs each job, so a
   job is reported as cut off only once the process running it has stopped
   (app/jobs/runners.py) -- with more than one server, a starting server
   used to fail the jobs of one still running. Existing jobs have no runner;
   any still active are from a server that has since stopped.

2. Values that come from outside -- venues, publishers, URLs, section
   headings read from PDFs, model names -- were VARCHAR(n). SQLite ignores
   the length, PostgreSQL enforces it and would refuse the row, so on
   PostgreSQL they become TEXT (a metadata-only change there). On SQLite
   nothing changes: its column types don't limit length.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

# (table, column, the old length)
_FREE_TEXT = (
    ("papers", "venue", 255),
    ("papers", "publisher", 255),
    ("papers", "url", 1024),
    ("papers", "pdf_path", 1024),
    ("papers", "fulltext_url", 1024),
    ("papers", "fulltext_error", 255),
    ("paper_chunks", "section", 255),
    ("paper_chunks", "embedding_ref", 255),
    ("research_profiles", "extraction_model", 255),
    ("workspaces", "combined_index_path", 1024),
    ("research_gaps", "generator_model", 255),
    ("research_directions", "generator_model", 255),
    ("llm_calls", "model", 128),
)


def upgrade() -> None:
    # each step skipped when already there (see 0021)
    inspector = sa.inspect(op.get_bind())
    if "runner_id" not in {c["name"] for c in inspector.get_columns("jobs")}:
        with op.batch_alter_table("jobs") as batch:
            batch.add_column(sa.Column("runner_id", sa.String(80), nullable=True))
    if "ix_jobs_runner_id" not in {i["name"] for i in inspector.get_indexes("jobs")}:
        op.create_index("ix_jobs_runner_id", "jobs", ["runner_id"])
    if not inspector.has_table("job_runners"):
        op.create_table(
            "job_runners",
            sa.Column("id", sa.String(80), primary_key=True),
            sa.Column("started_at", UTCDateTime(), nullable=False),
            sa.Column("heartbeat_at", UTCDateTime(), nullable=False),
        )
    if op.get_bind().dialect.name == "postgresql":
        for table, column, _length in _FREE_TEXT:
            op.alter_column(table, column, type_=sa.Text())


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # refused by PostgreSQL if a longer value has been stored since: nothing is cut silently
        for table, column, length in _FREE_TEXT:
            op.alter_column(table, column, type_=sa.String(length))
    op.drop_table("job_runners")
    op.drop_index("ix_jobs_runner_id", table_name="jobs")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("runner_id")
