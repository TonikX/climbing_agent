import unittest
import importlib.util
from pathlib import Path
from sqlalchemy import text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from tests import test_auth_postgres as fixtures

class MinimalPostgresTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.AuthPostgresTest.asyncSetUp
    asyncTearDown = fixtures.AuthPostgresTest.asyncTearDown
    login = fixtures.AuthPostgresTest.login

    async def test_minimal_attempt_keeps_unknowns_and_requires_belay(self):
        headers = await self.login("901")
        training = (await self.client.post("/api/v1/trainings", headers=headers, json={"date":"2026-10-26"})).json()
        url = f"/api/v1/trainings/{training['id']}/attempts"
        response = await self.client.post(url, headers=headers, json={"name":"Minimal route", "belay":"lead"})
        self.assertEqual(response.status_code, 201, response.text)
        row = response.json()
        for key in ("reached_top", "clean_ascent", "falls", "hangs", "notes"):
            self.assertIsNone(row[key], key)
        self.assertEqual(row["style"], "unknown")
        self.assertIsNone(row["route_snapshot"]["grade"])
        response = await self.client.post(url, headers=headers, json={"name":"Missing belay"})
        self.assertEqual(response.status_code, 422, response.text)
        response = await self.client.put("/api/v1/me/test-mode", headers=headers, json={"enabled":True})
        self.assertEqual(response.status_code, 403, response.text)

    async def test_migration_relaxes_outcomes_and_disables_nonadmin_mode(self):
        await self.login("901")
        await self.conn.execute(text("UPDATE users SET test_mode_enabled=true"))
        for column in ("reached_top", "clean_ascent"):
            await self.conn.execute(text(f"ALTER TABLE route_attempts ALTER COLUMN {column} SET NOT NULL"))
        spec = importlib.util.spec_from_file_location("minimal_migration", Path(__file__).parents[1]/"migrations/versions/20261026_0022_optional_attempt_outcome.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        def upgrade(conn):
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        await self.conn.run_sync(upgrade)
        enabled = await self.conn.scalar(text("SELECT count(*) FROM users WHERE role <> 'admin' AND test_mode_enabled"))
        self.assertEqual(enabled, 0)
        for column in ("reached_top", "clean_ascent"):
            nullable = await self.conn.scalar(text("SELECT is_nullable FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='route_attempts' AND column_name=:column"), {"column":column})
            self.assertEqual(nullable, "YES")

    async def test_clean_styles_store_zero_counters_on_create_and_edit(self):
        headers = await self.login("901")
        training = (await self.client.post("/api/v1/trainings", headers=headers, json={"date":"2026-10-26"})).json()
        url = f"/api/v1/trainings/{training['id']}/attempts"
        for style in ("flash", "redpoint", "onsight"):
            response = await self.client.post(url, headers=headers, json={"name":style, "style":style, "belay":"lead"})
            self.assertEqual(response.status_code, 201, response.text)
            row = response.json()
            self.assertEqual((row["falls"], row["hangs"], row["clean_ascent"]), (0, 0, True))
        response = await self.client.post(url, headers=headers, json={"name":"Edit", "belay":"lead"})
        row = response.json()
        version = (await self.client.get(f"/api/v1/trainings/{training['id']}", headers=headers)).json()["version"]
        response = await self.client.patch(f"/api/v1/attempts/{row['id']}", headers=headers,
            json={"expected_version":version, "style":"redpoint"})
        self.assertEqual(response.status_code, 200, response.text)
        row = (await self.conn.execute(text("SELECT falls,hangs,clean_ascent FROM route_attempts WHERE id=:id"), {"id":row["id"]})).one()
        self.assertEqual(tuple(row), (0, 0, True))
