"""Link the not_reached style to the explicit failure outcome."""
from alembic import op
import sqlalchemy as sa

revision = "20261026_0021"
down_revision = "20261022_0019"
branch_labels = depends_on = None


def upgrade():
    conn = op.get_bind()
    conn.execute(sa.text("SET LOCAL row_security=off"))
    conn.execute(sa.text("LOCK TABLE route_attempts IN ACCESS EXCLUSIVE MODE"))
    op.drop_constraint("ck_attempt_style", "route_attempts", type_="check")
    op.create_check_constraint("ck_attempt_style", "route_attempts",
        "style IN ('onsight','flash','redpoint','with_falls','with_hangs','not_reached','top_rope','unknown')")
    # Only explicit failed outcomes are backfilled; nonclean alone proves nothing about the top.
    conn.execute(sa.text("UPDATE route_attempts SET style='not_reached', clean_ascent=false WHERE reached_top=false"))
    op.create_check_constraint("ck_attempt_not_reached", "route_attempts",
        "(style = 'not_reached') = (reached_top IS FALSE)")


def downgrade():
    op.drop_constraint("ck_attempt_not_reached", "route_attempts", type_="check")
    op.execute("UPDATE route_attempts SET style='unknown' WHERE style='not_reached'")
    op.drop_constraint("ck_attempt_style", "route_attempts", type_="check")
    op.create_check_constraint("ck_attempt_style", "route_attempts",
        "style IN ('onsight','flash','redpoint','with_falls','with_hangs','top_rope','unknown')")
