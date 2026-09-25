"""Add backend-owned route attempt context.

Revision ID: 20260925_0004
Revises: 20260922_0003
"""

from alembic import op
import sqlalchemy as sa

revision = "20260925_0004"
down_revision = "20260922_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("route_attempts", sa.Column("route_session_key", sa.String()))
    op.add_column("route_attempts", sa.Column("attempt_number", sa.Integer()))
    op.add_column("route_attempts", sa.Column("high_point", sa.Integer()))
    op.add_column("route_attempts", sa.Column("total_moves", sa.Integer()))
    op.add_column("route_attempts", sa.Column("falls", sa.Integer()))
    op.create_index("ix_route_attempts_route_session_key", "route_attempts", ["route_session_key"])
    op.create_check_constraint("ck_attempt_number_positive", "route_attempts", "attempt_number IS NULL OR attempt_number > 0")
    op.create_check_constraint("ck_attempt_high_point_nonnegative", "route_attempts", "high_point IS NULL OR high_point >= 0")
    op.create_check_constraint("ck_attempt_total_moves_positive", "route_attempts", "total_moves IS NULL OR total_moves > 0")
    op.create_check_constraint("ck_attempt_falls_nonnegative", "route_attempts", "falls IS NULL OR falls >= 0")
    op.execute("""
        UPDATE route_attempts
        SET route_session_key = 'legacy_' || training_id || '_' || sequence,
            attempt_number = 1
    """)


def downgrade() -> None:
    op.drop_constraint("ck_attempt_falls_nonnegative", "route_attempts", type_="check")
    op.drop_constraint("ck_attempt_total_moves_positive", "route_attempts", type_="check")
    op.drop_constraint("ck_attempt_high_point_nonnegative", "route_attempts", type_="check")
    op.drop_constraint("ck_attempt_number_positive", "route_attempts", type_="check")
    op.drop_index("ix_route_attempts_route_session_key", table_name="route_attempts")
    op.drop_column("route_attempts", "falls")
    op.drop_column("route_attempts", "total_moves")
    op.drop_column("route_attempts", "high_point")
    op.drop_column("route_attempts", "attempt_number")
    op.drop_column("route_attempts", "route_session_key")
