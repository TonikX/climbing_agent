import importlib.util
from pathlib import Path
import unittest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from tests import test_auth_postgres as fixtures


class NotReachedPostgresTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.AuthPostgresTest.asyncSetUp
    asyncTearDown = fixtures.AuthPostgresTest.asyncTearDown
    login = fixtures.AuthPostgresTest.login

    async def test_style_only_input_infers_outcomes_and_can_be_corrected(self):
        headers = await self.login("901")
        training = (await self.client.post("/api/v1/trainings", headers=headers, json={"date": "2026-10-26"})).json()
        response = await self.client.post(f"/api/v1/trainings/{training['id']}/attempts", headers=headers,
            json={"name": "Test", "style": "not_reached", "belay": "lead", "falls": 2})
        self.assertEqual(response.status_code, 201, response.text)
        attempt = response.json()
        self.assertEqual((attempt["style"], attempt["reached_top"], attempt["clean_ascent"], attempt["falls"]),
                         ("not_reached", False, False, 2))
        version = (await self.client.get(f"/api/v1/trainings/{training['id']}", headers=headers)).json()["version"]
        edited = await self.client.patch(f"/api/v1/attempts/{attempt['id']}", headers=headers,
            json={"expected_version": version, "reached_top": True})
        self.assertEqual(edited.status_code, 200, edited.text)
        row = (await self.conn.execute(text("SELECT style,reached_top,clean_ascent FROM route_attempts"))).one()
        self.assertEqual(tuple(row), ("with_falls", True, False))

    async def test_migration_only_marks_explicit_failures_and_enforces_link(self):
        headers = await self.login("901")
        training = (await self.client.post("/api/v1/trainings", headers=headers, json={"date": "2026-10-26"})).json()
        for top in (False, True):
            response = await self.client.post(f"/api/v1/trainings/{training['id']}/attempts", headers=headers,
                json={"name": str(top), "reached_top": top, "clean_ascent": False, "style": "with_hangs", "belay": "lead", "hangs": 2})
            self.assertEqual(response.status_code, 201, response.text)
        await self.conn.execute(text("ALTER TABLE route_attempts DROP CONSTRAINT ck_attempt_not_reached"))
        await self.conn.execute(text("UPDATE route_attempts SET style='with_hangs' WHERE reached_top=false"))
        spec = importlib.util.spec_from_file_location("not_reached_migration", Path(__file__).parents[1] / "migrations/versions/20261026_0021_not_reached_style.py")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        def upgrade(conn):
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        await self.conn.run_sync(upgrade)
        rows = (await self.conn.execute(text("SELECT reached_top,style,hangs FROM route_attempts ORDER BY reached_top"))).all()
        self.assertEqual([tuple(row) for row in rows], [(False, "not_reached", 2), (True, "with_hangs", 2)])
        with self.assertRaises(Exception):
            async with self.conn.begin_nested():
                await self.conn.execute(text("UPDATE route_attempts SET reached_top=true WHERE style='not_reached'"))
