"""HTML structure, robots denial and idempotent public catalogue writes."""
import importlib.util
from pathlib import Path
import unittest

import httpx
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, func, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.allclimb import PublicHtmlClient
from app.allclimb_html import canonical_url, parse_html, parse_sitemap
from app.allclimb_store import upsert
from app.models import Base, Location, Section, Route, ExternalRef, User, TrainingSession
from app.import_models import CatalogImportRun
import test_outcome_postgres as outcome_tests

SOURCE = "https://allclimb.com/ru/list/Кабардино-Балкария/Джан-Туган/"
# Minimal factual fragment of the saved HTML; no articles, scripts or tokens.
HTML = '''<a class="news-preview-title" href="/ru/guides/Кабардино-Балкария/Джан-Туган/Ногоход/Изи/">
1. Изи <b>4B</b><span><i>Боулдер</i></span><span>(Джан-Туган. Ногоход)</span></a>
<button class="load-more" onclick="moreButtonPressed()">Загрузить ещё</button>'''


class AllClimbHtmlTest(unittest.IsolatedAsyncioTestCase):
    def test_actual_html_shape_parses_hierarchy_grade_and_marks_partial(self):
        page = parse_html(HTML, SOURCE, "RU")
        rows = {r.kind:r for r in page.records.values()}
        self.assertEqual((rows["location"].name, rows["section"].name, rows["route"].name), ("Джан-Туган", "Ногоход", "Изи"))
        self.assertEqual(rows["route"].grade, "4B")
        self.assertEqual(rows["location"].region, "Кабардино-Балкария")
        self.assertEqual(rows["route"].parent, rows["section"].url)
        self.assertIn("ajax_continuation_not_fetched", page.warnings)
        self.assertEqual(canonical_url(rows["route"].url), rows["route"].url)
        with self.assertRaises(ValueError):
            parse_html("<p>Login required</p>", SOURCE, "RU")
        with self.assertRaises(ValueError):
            canonical_url("https://other.example/ru/guides/a/b/")

    def test_sitemap_needs_reviewed_country_and_does_not_invent_routes(self):
        xml = '<urlset><url><loc>https://allclimb.com/ru/areas/Geyikbayırı_скалолазный_район</loc></url></urlset>'.encode()
        page = parse_sitemap(xml, {"Geyikbayırı":"TR"})
        record = next(iter(page.records.values()))
        self.assertEqual((record.kind, record.name, record.country), ("location", "Geyikbayırı", "TR"))
        with self.assertRaises(ValueError):
            parse_sitemap(xml, {})

    async def test_robots_denial_prevents_any_catalogue_request(self):
        seen = []
        def response(request):
            seen.append(request.url.path)
            return httpx.Response(200, text="User-agent: GPTBot\nDisallow: /\nUser-agent: *\nAllow: /\n")
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            with self.assertRaisesRegex(RuntimeError, "robots.txt"):
                await PublicHtmlClient(client).get(SOURCE)
        self.assertEqual(seen, ["/robots.txt"])


class AllClimbStoreTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = outcome_tests.PostgresOutcomeTest.asyncSetUp
    asyncTearDown = outcome_tests.PostgresOutcomeTest.asyncTearDown

    async def test_migration_restricted_role_repeat_import_and_private_data_unchanged(self):
        await self.conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(bind=self.conn, expire_on_commit=False) as session:
            user = User(name="Private", status="active")
            session.add(user)
            await session.flush()
            private = Location(owner_id=user.id, visibility="private", type="outdoor", name="Джан-Туган", country="Россия")
            session.add(private)
            await session.flush()
            for table, scope in {
                "locations":"visibility='public' OR owner_id=current_setting('app.user_id',true)",
                "sections":"location_id IN (SELECT id FROM locations)",
                "routes":"section_id IN (SELECT id FROM sections)",
                "external_refs":"location_id IN (SELECT id FROM locations) OR section_id IN (SELECT id FROM sections) OR route_id IN (SELECT id FROM routes)",
                "users":"id=current_setting('app.user_id',true)"}.items():
                await session.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
                await session.execute(text(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"))
                await session.execute(text(f"CREATE POLICY catalog_read ON {table} FOR SELECT USING ({scope})"))
            await session.execute(text("ALTER TABLE locations DROP COLUMN region"))
            await session.execute(text("DROP TABLE catalog_import_runs"))
            spec = importlib.util.spec_from_file_location("catalog_import_migration",
                Path(__file__).parents[1] / "migrations/versions/20261013_0015_catalog_import.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            def upgrade(conn):
                with Operations.context(MigrationContext.configure(conn)):
                    module.upgrade()
            await self.conn.run_sync(upgrade)
            schema = await session.scalar(text("SELECT current_schema()"))
            await session.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO climbing_catalog_importer'))
            await session.execute(text("SET LOCAL ROLE climbing_catalog_importer"))
            await session.execute(text("SELECT set_config('app.user_id',:uid,true)"), {"uid":user.id})
            records = parse_html(HTML, SOURCE, "RU").records
            first = await upsert(session, records)
            self.assertEqual(first["created"], 3)
            stable = (await session.scalars(select(ExternalRef.external_id))).all()
            again = await upsert(session, records)
            self.assertEqual(again, {"created":0, "updated":0, "unchanged":3})
            self.assertEqual((await session.scalars(select(ExternalRef.external_id))).all(), stable)
            self.assertEqual(await session.scalar(select(func.count(Location.id))), 1)
            self.assertIsNone(await session.scalar(select(Location.id).where(Location.id==private.id)))
            self.assertEqual(await session.scalar(select(func.count(User.id))), 0)
            with self.assertRaises(ProgrammingError):
                async with session.begin_nested():
                    await session.execute(select(TrainingSession))
            await session.execute(text("RESET ROLE"))
            self.assertEqual(await session.scalar(select(Location.name).where(Location.id==private.id)), "Джан-Туган")
