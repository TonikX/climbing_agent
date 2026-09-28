"""A fall, hang or rope rest always makes an ascent non-clean.

Revision ID: 20260929_0009
Revises: 20260928_0008
"""
from alembic import op

revision = "20260929_0009"
down_revision = "20260928_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE route_attempts
        SET clean_ascent = false
        WHERE falls > 0 OR
          regexp_replace(
            lower(coalesce(notes, '')),
            'без[[:space:]]+(срыв|завис)[^[:space:],.;]*([[:space:]]+и[[:space:]]+(срыв|завис)[^[:space:],.;]*)?', '', 'g'
          ) ~ '(срыв|сорв|завис|повис|с[[:space:]]+перерыв)'
    """)


def downgrade():
    # Reapply the style inference from 0007; 0008 still fixes explicit clean notes.
    op.execute("""
        UPDATE route_attempts
        SET reached_top = true, clean_ascent = true
        WHERE style IN ('onsight', 'flash', 'redpoint')
          AND (falls IS NULL OR falls = 0)
    """)
