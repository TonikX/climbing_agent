"""Separate reaching the top from a clean ascent, preserving legacy result.

Revision ID: 20260928_0006
Revises: 20260925_0005
"""
from alembic import op
import sqlalchemy as sa

revision = "20260928_0006"
down_revision = "20260925_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("route_attempts", sa.Column("reached_top", sa.Boolean(), nullable=True))
    op.add_column("route_attempts", sa.Column("clean_ascent", sa.Boolean(), nullable=True))
    # Neither legacy send nor style proves absence of hangs. Keep clean unknown.
    op.execute("""UPDATE route_attempts SET
        reached_top = CASE WHEN result = 'send' THEN true ELSE NULL END,
        clean_ascent = CASE WHEN falls > 0 OR result = 'project' THEN false ELSE NULL END
    """)
    op.create_check_constraint("ck_attempt_clean_top", "route_attempts", "clean_ascent IS NOT TRUE OR reached_top IS TRUE")
    op.create_check_constraint("ck_attempt_clean_falls", "route_attempts", "clean_ascent IS NOT TRUE OR falls IS NULL OR falls = 0")
    op.create_check_constraint("ck_attempt_no_top", "route_attempts", "reached_top IS NOT FALSE OR clean_ascent IS FALSE")


def downgrade():
    for name in ("ck_attempt_no_top", "ck_attempt_clean_falls", "ck_attempt_clean_top"):
        op.drop_constraint(name, "route_attempts", type_="check")
    op.drop_column("route_attempts", "clean_ascent")
    op.drop_column("route_attempts", "reached_top")
