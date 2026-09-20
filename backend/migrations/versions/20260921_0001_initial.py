"""Initial users, training sessions and route attempts.

Revision ID: 20260921_0001
Revises:
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260921_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("timezone", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "external_refs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("system", sa.String(50), nullable=False),
        sa.Column("external_id", sa.String(300), nullable=False),
        sa.UniqueConstraint("system", "external_id", name="uq_external_identity"),
    )
    op.create_index("ix_external_refs_user_id", "external_refs", ["user_id"])
    op.create_table(
        "training_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("environment", sa.String(20), nullable=False),
        sa.Column("duration_minutes", sa.Integer()),
        sa.Column("physical_state", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("weather", postgresql.JSONB()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_training_sessions_user_id", "training_sessions", ["user_id"])
    op.create_index(
        "uq_active_training_per_user",
        "training_sessions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "route_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("training_id", sa.String(), sa.ForeignKey("training_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_id", sa.String()),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("result", sa.String(20), nullable=False),
        sa.Column("style", sa.String(20), nullable=False),
        sa.Column("belay", sa.String(20), nullable=False),
        sa.Column("feel", sa.String(20), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("route_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("training_id", "sequence", name="uq_attempt_sequence"),
    )
    op.create_index("ix_route_attempts_training_id", "route_attempts", ["training_id"])


def downgrade() -> None:
    op.drop_table("route_attempts")
    op.drop_table("training_sessions")
    op.drop_table("external_refs")
    op.drop_table("users")
