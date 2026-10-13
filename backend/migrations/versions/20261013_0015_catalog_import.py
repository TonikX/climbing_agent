"""Importer reports and a role that can write only the public source catalogue."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_0015"
down_revision = "20261013_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("locations", sa.Column("region", sa.String(200)))
    op.create_table("catalog_import_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("report", sa.dialects.postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.CheckConstraint("status IN ('running','partial','succeeded','failed','interrupted')", name="ck_catalog_import_status"))
    op.execute("""DO $$ BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='climbing_catalog_importer') THEN
            CREATE ROLE climbing_catalog_importer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
        END IF; END $$""")
    scopes = {
        "locations": "visibility='public' AND owner_id IS NULL",
        "sections": "EXISTS(SELECT FROM locations l WHERE l.id=location_id AND l.visibility='public' AND l.owner_id IS NULL)",
        "routes": "EXISTS(SELECT FROM sections s JOIN locations l ON l.id=s.location_id WHERE s.id=section_id AND l.visibility='public' AND l.owner_id IS NULL)",
        "external_refs": "system='allclimb' AND (location_id IN (SELECT id FROM locations WHERE visibility='public') OR section_id IN (SELECT id FROM sections) OR route_id IN (SELECT id FROM routes))",
    }
    for table, scope in scopes.items():
        # Restrictive guard also blocks inherited PUBLIC owner policies if app.user_id is set.
        op.execute(f"CREATE POLICY importer_scope ON {table} AS RESTRICTIVE FOR ALL TO climbing_catalog_importer USING ({scope}) WITH CHECK ({scope})")
        op.execute(f"CREATE POLICY importer_insert ON {table} FOR INSERT TO climbing_catalog_importer WITH CHECK ({scope})")
        op.execute(f"CREATE POLICY importer_update ON {table} FOR UPDATE TO climbing_catalog_importer USING ({scope}) WITH CHECK ({scope})")
        op.execute(f"GRANT SELECT,INSERT,UPDATE ON {table} TO climbing_catalog_importer")
    # Existing catalogue read policies reference users. RLS exposes no user without app.user_id.
    op.execute("GRANT SELECT ON users TO climbing_catalog_importer")
    op.execute("CREATE POLICY importer_no_identity ON users AS RESTRICTIVE FOR SELECT TO climbing_catalog_importer USING (false)")
    op.execute("ALTER TABLE catalog_import_runs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE catalog_import_runs FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY importer_runs ON catalog_import_runs TO climbing_catalog_importer USING (true) WITH CHECK (true)")
    op.execute("GRANT SELECT,INSERT,UPDATE ON catalog_import_runs TO climbing_catalog_importer")


def downgrade():
    raise RuntimeError("Use a reviewed forward migration; preserve imported catalogue identities")
