"""Run against PostgreSQL: isolated schemas, all changes rolled back."""
import importlib.util
from pathlib import Path
import unittest
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import engine
from app.models import Base
from app.tool_service import _start, _append, _update_attempt, _get_current, _save
from app.schemas import AttemptCreate
from app.service import append_attempt


class PostgresOutcomeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await engine.connect()
        self.tx = await self.conn.begin()
        schema = "outcome_test_" + uuid4().hex
        await self.conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await self.conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))

    async def asyncTearDown(self):
        await self.tx.rollback()
        await self.conn.close()
        await engine.dispose()

    async def test_migration_preserves_unknown_and_original_result(self):
        await self.conn.execute(text("CREATE TABLE route_attempts (id int, result text, falls int, style text, notes text)"))
        await self.conn.execute(text("""INSERT INTO route_attempts VALUES
            (1,'send',0,'flash',NULL),
            (2,'send',2,'unknown','один срыв, но долез'),
            (3,'project',NULL,'unknown','долез до верха, 1 срыв'),
            (4,'unknown',NULL,'unknown','Чистый пролаз с первой попытки'),
            (7,'send',NULL,'unknown','Чисто, без зависаний, с первой попытки'),
            (8,'send',NULL,'unknown','Сорвался по пути, но долез до верха')"""))
        path = Path(__file__).parents[1] / "migrations/versions/20260928_0006_attempt_outcomes.py"
        spec = importlib.util.spec_from_file_location("outcome_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        def upgrade(conn):
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        await self.conn.run_sync(upgrade)
        rows = (await self.conn.execute(text("SELECT result,reached_top,clean_ascent FROM route_attempts ORDER BY id"))).all()
        self.assertEqual([tuple(row) for row in rows], [
            ("send", True, None), ("send", True, False), ("project", None, False), ("unknown", None, None),
            ("send", True, None), ("send", True, None)])
        path = Path(__file__).parents[1] / "migrations/versions/20260928_0007_infer_historical_outcomes.py"
        spec = importlib.util.spec_from_file_location("outcome_inference_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        await self.conn.run_sync(upgrade)
        rows = (await self.conn.execute(text("SELECT result,reached_top,clean_ascent FROM route_attempts ORDER BY id"))).all()
        self.assertEqual([tuple(row) for row in rows], [
            ("send", True, True), ("send", True, False), ("project", True, False), ("unknown", True, True),
            ("send", True, False), ("send", True, None)])
        path = Path(__file__).parents[1] / "migrations/versions/20260928_0008_fix_note_inference.py"
        spec = importlib.util.spec_from_file_location("note_inference_fix_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        await self.conn.run_sync(upgrade)
        rows = (await self.conn.execute(text("SELECT result,reached_top,clean_ascent FROM route_attempts ORDER BY id"))).all()
        self.assertEqual([tuple(row) for row in rows], [
            ("send", True, True), ("send", True, False), ("project", True, False), ("unknown", True, True),
            ("send", True, True), ("send", True, False)])
        for sql in (
            "INSERT INTO route_attempts (id,reached_top,clean_ascent) VALUES (5,false,true)",
            "INSERT INTO route_attempts (id,reached_top,clean_ascent,falls) VALUES (6,true,true,1)",
        ):
            with self.assertRaises(IntegrityError):
                async with self.conn.begin_nested():
                    await self.conn.execute(text(sql))

    async def test_tool_rest_update_and_summary_share_outcomes(self):
        await self.conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(bind=self.conn, expire_on_commit=False) as session:
            user = {"name": "Outcome test"}
            training = await _start(session, {"user": user, "date": "2026-09-28"})
            session.expire_all()
            first = await _append(session, {"user": user, "date": "2026-09-28", "name": "Route A",
                                           "reachedTop": True, "falls": 2})
            self.assertEqual(first["outcome"]["cleanAscent"], False)
            session.expire_all()
            await _update_attempt(session, {"user": user, "attemptId": first["attemptId"], "falls": 0, "cleanAscent": True})
            await session.flush()
            session.expire_all()
            current = await _get_current(session, {"user": user, "detail": "full"})
            self.assertEqual(current["summary"]["completedRoutes"], 1)
            session.expire_all()
            await _save(session, {"user": user, "date": "2026-09-28", "mergeIntoActive": True,
                                 "routes": [{"name": "Route A", "cleanAscent": None}]})
            session.expire_all()
            current = await _get_current(session, {"user": user})
            self.assertEqual(current["summary"]["completedRoutes"], 0)
            uid = await session.scalar(text("SELECT id FROM users LIMIT 1"))
            attempt = await append_attempt(session, uid, training["trainingId"],
                                           AttemptCreate(name="Route B", clean_ascent=True))
            self.assertTrue(attempt.reached_top)
            self.assertTrue(attempt.clean_ascent)
