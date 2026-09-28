"""Recover historical outcomes from style and explicit Russian notes.

Revision ID: 20260928_0007
Revises: 20260928_0006
"""
from alembic import op

revision = "20260928_0007"
down_revision = "20260928_0006"
branch_labels = None
depends_on = None


def upgrade():
    # Style is a climbing result: onsight, flash and redpoint are clean ascents.
    op.execute("""
        UPDATE route_attempts
        SET reached_top = true, clean_ascent = true
        WHERE style IN ('onsight', 'flash', 'redpoint')
          AND (falls IS NULL OR falls = 0)
    """)
    # Restore facts only when the note says them explicitly.
    op.execute("""
        UPDATE route_attempts
        SET reached_top = true
        WHERE lower(coalesce(notes, '')) ~
              '(долез[^.]{0,40}(до )?(верха|конца)|после срыва долез|но долез)'
    """)
    op.execute("""
        UPDATE route_attempts
        SET clean_ascent = false
        WHERE clean_ascent IS NULL
          AND lower(coalesce(notes, '')) ~ '(срыв|зависан|с перерыв)'
    """)
    op.execute("""
        UPDATE route_attempts
        SET reached_top = true, clean_ascent = true
        WHERE clean_ascent IS NULL
          AND lower(coalesce(notes, '')) ~
              '(чист(ый|о|ый пролаз)|без зависан|без срыв|с первой попытки)'
          AND lower(coalesce(notes, '')) !~
              '(чистого пролаза не было|не чист|срыв|зависан|с перерыв)'
          AND (falls IS NULL OR falls = 0)
    """)


def downgrade():
    # Return to the conservative mapping defined by revision 0006.
    op.execute("""
        UPDATE route_attempts SET
            reached_top = CASE WHEN result = 'send' THEN true ELSE NULL END,
            clean_ascent = CASE WHEN falls > 0 OR result = 'project' THEN false ELSE NULL END
    """)
