"""Allow minimal attempts without inventing outcome facts."""
from alembic import op
import sqlalchemy as sa
revision = "20261026_0022"
down_revision = "20261026_0021"
branch_labels = depends_on = None

def upgrade():
    for column in ("reached_top", "clean_ascent"):
        op.alter_column("route_attempts", column, existing_type=sa.Boolean(), nullable=True)
    op.execute("UPDATE users SET test_mode_enabled=false WHERE role <> 'admin'")

def downgrade():
    for column in ("reached_top", "clean_ascent"):
        op.alter_column("route_attempts", column, existing_type=sa.Boolean(), nullable=False)
