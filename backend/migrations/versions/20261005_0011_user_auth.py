"""User status and revocable, hashed bearer sessions.

Revision ID: 20261005_0011
Revises: 20260929_0010
"""
from alembic import op
import sqlalchemy as sa

revision = "20261005_0011"
down_revision = "20260929_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("status", sa.String(20), nullable=False, server_default="active"))
    op.create_check_constraint("ck_user_status", "users", "status IN ('active', 'blocked')")
    op.create_table("auth_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])


def downgrade():
    op.drop_table("auth_sessions")
    op.drop_constraint("ck_user_status", "users", type_="check")
    op.drop_column("users", "status")
