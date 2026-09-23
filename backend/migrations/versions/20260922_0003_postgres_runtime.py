"""Store all runtime training fields in PostgreSQL.

Revision ID: 20260922_0003
Revises: 20260922_0002
"""

from alembic import op
import sqlalchemy as sa

revision = "20260922_0003"
down_revision = "20260922_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("training_sessions", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.alter_column("locations", "country", type_=sa.String(200), existing_type=sa.String(2))


def downgrade() -> None:
    op.alter_column("locations", "country", type_=sa.String(2), existing_type=sa.String(200))
    op.drop_column("training_sessions", "started_at")
