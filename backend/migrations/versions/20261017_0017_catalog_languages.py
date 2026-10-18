"""Explicit English and native catalogue names; preserve existing identities."""
from alembic import op
import sqlalchemy as sa

revision = "20261017_0017"
down_revision = "20261015_0016"
branch_labels = depends_on = None


def upgrade():
    for table in ("sections", "routes"):
        for column in ("name_en", "name_native"):
            op.add_column(table, sa.Column(column, sa.String(200), nullable=True))
            op.execute(f"CREATE INDEX ix_{table}_{column}_search ON {table} USING gin (catalog_normalize({column}) public.gin_trgm_ops)")
            op.execute(f"CREATE INDEX ix_{table}_{column}_exact ON {table} (catalog_normalize({column}))")
    # The language of old names is unknown. Do not label or translate them heuristically.


def downgrade():
    raise RuntimeError("Preserve translated catalogue names; use a reviewed forward migration")
