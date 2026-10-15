"""Indexed catalogue search and private, confirmed alternate spellings."""
from alembic import op
import sqlalchemy as sa

revision = "20261015_0016"
down_revision = "20261013_0015"
branch_labels = depends_on = None


def search_functions():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
    op.execute("""CREATE OR REPLACE FUNCTION catalog_normalize(value text) RETURNS text
    LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$
      SELECT regexp_replace(translate(lower(replace(value,'İ','I')),
      'ığşçöüâîûáàäãåéèêëíìïóòôõúùÿñё',
      'igscouaiuaaaaaeeeeiiioooouuynе'), '[^[:alnum:]]+', '', 'g')
    $$""")


def upgrade():
    search_functions()
    op.create_table("catalog_aliases",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("owner_id", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("location_id", sa.String(), sa.ForeignKey("locations.id", ondelete="CASCADE")),
        sa.Column("section_id", sa.String(), sa.ForeignKey("sections.id", ondelete="CASCADE")),
        sa.Column("route_id", sa.String(), sa.ForeignKey("routes.id", ondelete="CASCADE")),
        sa.CheckConstraint("num_nonnulls(location_id,section_id,route_id)=1", name="ck_alias_target"))
    for table in ("locations", "sections", "routes", "catalog_aliases"):
        op.execute(f"CREATE INDEX ix_{table}_search ON {table} USING gin (catalog_normalize(name) public.gin_trgm_ops)")
        op.execute(f"CREATE INDEX ix_{table}_search_exact ON {table} (catalog_normalize(name))")
    op.create_index("ix_alias_owner", "catalog_aliases", ["owner_id"])
    for column in ("location_id", "section_id", "route_id"):
        op.create_index("ix_alias_"+column, "catalog_aliases", [column])
    scope = """owner_id=current_setting('app.user_id',true)
      AND EXISTS(SELECT FROM users u WHERE u.id=owner_id AND u.status='active') AND (
      location_id IN (SELECT id FROM locations) OR section_id IN (SELECT id FROM sections)
      OR route_id IN (SELECT id FROM routes))"""
    op.execute("ALTER TABLE catalog_aliases ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE catalog_aliases FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY alias_owner ON catalog_aliases USING ({scope}) WITH CHECK ({scope})")
    # Importer inherits PUBLIC policies; it must not access personal aliases even with a spoofed context.
    op.execute("CREATE POLICY importer_no_aliases ON catalog_aliases AS RESTRICTIVE TO climbing_catalog_importer USING (false) WITH CHECK (false)")
    for role in ("climbing_runtime", "climbing_control_login"):
        op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT FROM pg_roles WHERE rolname='{role}') THEN
          GRANT SELECT,INSERT,UPDATE,DELETE ON catalog_aliases TO {role}; END IF; END $$""")


def downgrade():
    raise RuntimeError("Preserve confirmed aliases; use a reviewed forward migration")
