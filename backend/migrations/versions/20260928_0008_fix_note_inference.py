"""Give explicit clean phrases priority and recognize Russian 'сорвался'.

Revision ID: 20260928_0008
Revises: 20260928_0007
"""
from alembic import op

revision = "20260928_0008"
down_revision = "20260928_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        UPDATE route_attempts
        SET reached_top = true, clean_ascent = true
        WHERE lower(coalesce(notes, '')) ~
              '(чистый пролаз|(^|[[:space:],.;])чисто([[:space:],.;]|$)|без зависан|без срыв)'
          AND lower(coalesce(notes, '')) !~ '(чистого пролаза не было|не чист)'
          AND (falls IS NULL OR falls = 0)
    """)
    op.execute("""
        UPDATE route_attempts
        SET clean_ascent = false
        WHERE clean_ascent IS NULL
          AND lower(coalesce(notes, '')) ~ '(срыв|сорв|зависан|с перерыв)'
    """)


def downgrade():
    # Reproduce revision 0007's ordering for note-derived rows.
    op.execute("""
        UPDATE route_attempts
        SET clean_ascent = CASE
            WHEN style IN ('onsight', 'flash', 'redpoint') AND (falls IS NULL OR falls = 0) THEN true
            WHEN falls > 0 OR result = 'project' THEN false
            WHEN lower(coalesce(notes, '')) ~ '(срыв|зависан|с перерыв)' THEN false
            WHEN lower(coalesce(notes, '')) ~ '(чист(ый|о|ый пролаз)|без зависан|без срыв|с первой попытки)'
                 AND lower(coalesce(notes, '')) !~ '(чистого пролаза не было|не чист|срыв|зависан|с перерыв)'
                 AND (falls IS NULL OR falls = 0) THEN true
            ELSE NULL
        END
    """)
