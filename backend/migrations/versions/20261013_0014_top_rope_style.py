"""Add the explicit Upper style without rewriting existing ascent facts."""
from alembic import op

revision = "20261013_0014"
down_revision = "20261012_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("ck_attempt_style", "route_attempts", type_="check")
    op.create_check_constraint("ck_attempt_style", "route_attempts",
        "style IN ('onsight','flash','redpoint','with_falls','with_hangs','top_rope','unknown')")


def downgrade():
    raise RuntimeError("Use a reviewed forward migration; preserve recorded top_rope styles")
