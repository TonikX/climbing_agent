"""Separate upper belay from style and require known outcome facts.

Unknown historical outcomes must be reviewed before this migration can commit.
No fall/hang is interpreted as evidence of whether the climber reached the top.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261022_0020"
down_revision = "20261022_0019"
branch_labels = depends_on = None


def upgrade():
    conn = op.get_bind()
    previous_rls = conn.execute(sa.text("SHOW row_security")).scalar_one()
    conn.execute(sa.text("SET LOCAL row_security=off"))  # Fail rather than silently checking only one owner's rows.
    # Freeze writes while checking/backfilling, including a non-public installation.
    conn.execute(sa.text("LOCK TABLE route_attempts IN ACCESS EXCLUSIVE MODE"))
    conflicts = conn.execute(sa.text("""SELECT count(*) FROM route_attempts
        WHERE style='top_rope' AND belay NOT IN ('top_rope','unknown')""")).scalar_one()
    if conflicts:
        raise RuntimeError(f"Review {conflicts} top_rope style / belay conflicts before migration")
    conn.execute(sa.text("""UPDATE route_attempts SET
        belay='top_rope',
        style=CASE WHEN falls > 0 THEN 'with_falls' WHEN hangs > 0 THEN 'with_hangs' ELSE 'unknown' END
        WHERE style='top_rope'"""))
    # Only recover facts that follow from existing structured facts or legacy send.
    conn.execute(sa.text("""UPDATE route_attempts SET clean_ascent=false
        WHERE reached_top=false OR falls>0 OR hangs>0 OR style IN ('with_falls','with_hangs')"""))
    conn.execute(sa.text("""UPDATE route_attempts SET reached_top=true
        WHERE reached_top IS NULL AND (clean_ascent=true OR result='send')"""))
    unresolved = conn.execute(sa.text("""SELECT count(*) FROM route_attempts
        WHERE reached_top IS NULL OR clean_ascent IS NULL OR belay IS NULL OR belay='unknown'""")).scalar_one()
    if unresolved:
        raise RuntimeError(f"Review {unresolved} incomplete historical attempts before migration; "
                           "specify reached_top, clean_ascent and belay. All changes are rolled back.")
    op.drop_constraint("ck_attempt_style", "route_attempts", type_="check")
    op.create_check_constraint("ck_attempt_style", "route_attempts",
        "style IN ('onsight','flash','redpoint','with_falls','with_hangs','unknown')")
    op.drop_constraint("ck_attempt_belay", "route_attempts", type_="check")
    op.create_check_constraint("ck_attempt_belay", "route_attempts",
        "belay IN ('lead','top_rope','auto_belay','bouldering')")
    op.alter_column("route_attempts", "reached_top", existing_type=sa.Boolean(), nullable=False)
    op.alter_column("route_attempts", "clean_ascent", existing_type=sa.Boolean(), nullable=False)
    op.alter_column("route_attempts", "belay", existing_type=sa.String(20), server_default=None)
    conn.execute(sa.text("SET LOCAL row_security=" + ("off" if previous_rls == "off" else "on")))


def downgrade():
    op.alter_column("route_attempts", "reached_top", existing_type=sa.Boolean(), nullable=True)
    op.alter_column("route_attempts", "clean_ascent", existing_type=sa.Boolean(), nullable=True)
    op.drop_constraint("ck_attempt_style", "route_attempts", type_="check")
    op.create_check_constraint("ck_attempt_style", "route_attempts",
        "style IN ('onsight','flash','redpoint','with_falls','with_hangs','top_rope','unknown')")
    op.drop_constraint("ck_attempt_belay", "route_attempts", type_="check")
    op.create_check_constraint("ck_attempt_belay", "route_attempts",
        "belay IN ('lead','top_rope','auto_belay','bouldering','unknown')")
    # Corrected data stays corrected; use the deployment backup to restore original facts.
