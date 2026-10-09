"""Email + password sign-in with emailed one-time codes

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-09

Mirrors app/db/models.py (UserORM, AuthSessionORM, AuthChallengeORM,
RateLimitORM).

Until now any password signed in to any email, and an unknown email made a
new account. This adds what real sign-in needs, without touching existing
data: every user keeps their id, email, workspaces and keys.

- users: name, password_hash, email_verified_at, password_changed_at, all
  nullable. An account made before this has no password; its owner sets one
  through "Forgot password", which proves the email is theirs.
- users: an index on lower(email). Sign-in matches an email whatever its
  capitalisation, and accounts saved before that may differ in case, so the
  index is not unique.
- auth_sessions: signed-in browsers (only a hash of each token is stored).
- auth_challenges: emailed codes in flight (only an HMAC of each code).
- rate_limits: request counters shared by every server process.

Purely additive; downgrade drops the new tables and columns. Each step is
skipped when what it adds is already there (a development server makes
missing tables itself), so the migration also completes on such a database.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from app.db.types import UTCDateTime

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table) if i["name"]}


def upgrade() -> None:
    present = _columns("users")
    new_columns = [
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("email_verified_at", UTCDateTime(), nullable=True),
        sa.Column("password_changed_at", UTCDateTime(), nullable=True),
    ]
    with op.batch_alter_table("users") as batch:
        for column in new_columns:
            if column.name not in present:
                batch.add_column(column)
    if "ix_users_email_lower" not in _indexes("users"):
        op.create_index("ix_users_email_lower", "users", [sa.text("lower(email)")])

    if not _has_table("auth_sessions"):
        _create_auth_tables()
    if not _has_table("auth_challenges"):
        _create_challenges()
    if not _has_table("rate_limits"):
        _create_rate_limits()


def _create_auth_tables() -> None:
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_seen_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])


def _create_challenges() -> None:
    op.create_table(
        "auth_challenges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("send_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_sent_at", UTCDateTime(), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("consumed_at", UTCDateTime(), nullable=True),
    )
    op.create_index("ix_auth_challenges_email_purpose", "auth_challenges", ["email", "purpose"])


def _create_rate_limits() -> None:
    op.create_table(
        "rate_limits",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("window_start", UTCDateTime(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("rate_limits")
    op.drop_index("ix_auth_challenges_email_purpose", table_name="auth_challenges")
    op.drop_table("auth_challenges")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_email_lower", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("password_changed_at")
        batch.drop_column("email_verified_at")
        batch.drop_column("password_hash")
        batch.drop_column("name")
