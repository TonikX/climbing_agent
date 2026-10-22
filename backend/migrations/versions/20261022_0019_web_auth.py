"""Browser sessions and single-use Telegram OIDC handshakes."""
from alembic import op
import sqlalchemy as sa

revision = "20261022_0019"
down_revision = "20261020_0018"
branch_labels = depends_on = None


def upgrade():
    op.add_column("auth_sessions", sa.Column("channel", sa.String(10), nullable=False, server_default="bot"))
    op.create_check_constraint("ck_auth_session_channel", "auth_sessions", "channel IN ('bot', 'web')")
    op.create_table("web_login_states",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("verifier", sa.String(128), nullable=False),
        sa.Column("nonce", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_web_login_states_browser_hash", "web_login_states", ["browser_hash"])
    op.create_index("ix_web_login_states_expires_at", "web_login_states", ["expires_at"])
    op.execute("ALTER TABLE web_login_states ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE web_login_states FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY control_only ON web_login_states TO climbing_control USING (true) WITH CHECK (true)")
    op.execute("GRANT SELECT,INSERT,DELETE ON web_login_states TO climbing_control_login")


def downgrade():
    op.drop_table("web_login_states")
    op.drop_constraint("ck_auth_session_channel", "auth_sessions", type_="check")
    op.drop_column("auth_sessions", "channel")
