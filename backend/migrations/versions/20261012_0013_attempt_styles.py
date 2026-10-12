"""Explicit non-clean ascent styles; preserve historical unknown facts."""
from alembic import op

revision = "20261012_0013"
down_revision = "20261010_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_attempt_style", "route_attempts", type_="check")
    op.create_check_constraint("ck_attempt_style", "route_attempts",
                              "style IN ('onsight','flash','redpoint','with_falls','with_hangs','unknown')")
    op.create_check_constraint("ck_attempt_nonclean_style", "route_attempts",
                              "clean_ascent IS NOT TRUE OR style NOT IN ('with_falls','with_hangs')")


def downgrade():
    # Rewriting historical facts on rollback would be destructive.
    raise RuntimeError("Use a reviewed forward migration")
