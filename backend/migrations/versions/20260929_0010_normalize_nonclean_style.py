"""Remove clean-only styles from attempts known to be non-clean.

Revision ID: 20260929_0010
Revises: 20260929_0009
"""
from alembic import op

revision = "20260929_0010"
down_revision = "20260929_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE route_attempts
        SET style = 'unknown'
        WHERE clean_ascent IS FALSE AND style IN ('onsight', 'flash', 'redpoint')
    """)


def downgrade():
    pass
