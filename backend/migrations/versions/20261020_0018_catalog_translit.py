"""Transliteration search indexes, without changing catalogue identities."""
from alembic import op

revision = "20261020_0018"
down_revision = "20261017_0017"
branch_labels = depends_on = None


def upgrade():
    op.execute(SQL)
    for table in ("locations", "sections", "routes", "catalog_aliases"):
        columns = ("name", "name_en", "name_native") if table in ("sections", "routes") else ("name",)
        for column in columns:
            op.execute(f"CREATE INDEX ix_{table}_{column}_translit ON {table} USING gin (catalog_translit({column}) public.gin_trgm_ops)")


def downgrade():
    for table in ("locations", "sections", "routes", "catalog_aliases"):
        columns = ("name", "name_en", "name_native") if table in ("sections", "routes") else ("name",)
        for column in columns:
            op.execute(f"DROP INDEX ix_{table}_{column}_translit")
    op.execute("DROP FUNCTION catalog_translit(text)")


SQL = "CREATE OR REPLACE FUNCTION catalog_translit(value text) RETURNS text\nLANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $$ SELECT regexp_replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(replace(regexp_replace(translate(replace(replace(lower(replace(value,'İ','I')),'ş','sh'),'ç','ch'),\n 'ığşçöüâîûáàäãåéèêëíìïóòôõúùÿñё',\n 'igscouaiuaaaaaeeeeiiioooouuynе'), '[^[:alnum:]]+', '', 'g'),'а','a'),'б','b'),'в','v'),'г','g'),'д','d'),'е','e'),'ж','zh'),'з','z'),'и','i'),'й','i'),'к','k'),'л','l'),'м','m'),'н','n'),'о','o'),'п','p'),'р','r'),'с','s'),'т','t'),'у','u'),'ф','f'),'х','kh'),'ц','ts'),'ч','ch'),'ш','sh'),'щ','shch'),'ъ',''),'ы','y'),'ь',''),'э','e'),'ю','yu'),'я','ya'),'kh','h'),'y','i'),'dzh','j'),'zh','j'),'c(?!h)','j','g') $$"
