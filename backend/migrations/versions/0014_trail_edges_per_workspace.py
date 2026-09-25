"""paper_relationships: per-workspace trail edges

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-26

Mirrors app/db/models.py (PaperRelationshipORM).

Importing a discovery run into a workspace used to re-stamp the run's trail
rows with the new workspace and owner -- so a second workspace created from
the same run *moved* every connection, with its accept/reject decisions,
out of the first one. The old unique key (run, source, target, type) left
no room for a second workspace's copy.

Now: the trail pipeline's rows are the run's *primaries* (`copied_from`
NULL), still unique per (run, source, target, type) via a partial unique
index; the first workspace to import a run owns them as before, and every
later workspace gets its own copy (`copied_from` = the primary's id), unique
per (run, source, target, type, workspace). Existing rows are all
primaries, so no data changes on upgrade. Downgrade drops the copies (the
old key cannot hold them) and restores the old key.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_KEY = ["run_id", "source_paper_id", "target_paper_id", "relationship_type"]
_PRIMARY = sa.text("copied_from IS NULL")


def upgrade() -> None:
    with op.batch_alter_table("paper_relationships", recreate="always") as batch:
        batch.add_column(sa.Column("copied_from", sa.String(64), nullable=True))
        batch.drop_constraint("ux_paper_rel_run_src_tgt_type", type_="unique")
        batch.create_unique_constraint("ux_paper_rel_run_src_tgt_type_ws", [*_KEY, "workspace_id"])
    op.create_index(
        "ux_paper_rel_primary",
        "paper_relationships",
        _KEY,
        unique=True,
        sqlite_where=_PRIMARY,
        postgresql_where=_PRIMARY,
    )


def downgrade() -> None:
    op.execute("DELETE FROM paper_relationships WHERE copied_from IS NOT NULL")
    op.drop_index("ux_paper_rel_primary", table_name="paper_relationships")
    with op.batch_alter_table("paper_relationships", recreate="always") as batch:
        batch.drop_constraint("ux_paper_rel_run_src_tgt_type_ws", type_="unique")
        batch.create_unique_constraint("ux_paper_rel_run_src_tgt_type", _KEY)
        batch.drop_column("copied_from")
