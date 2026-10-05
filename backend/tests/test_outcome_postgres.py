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
from fastapi import HTTPException

from app.db import engine
from app.models import Base, RouteAttempt, User
from app.tool_service import _start, _append, _update_attempt, _get_current, _save, _delete_attempt, execute_tool
from app.schemas import AttemptCreate
from app.service import append_attempt
from app.main import start_training_endpoint, append_attempt_endpoint, finish_training_endpoint
from app.schemas import TrainingCreate, FinishTraining
from datetime import date


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
            (8,'send',NULL,'unknown','Сорвался по пути, но долез до верха'),
            (9,'send',NULL,'redpoint','Долез до конца с перерывом')"""))
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
            ("send", True, None), ("send", True, None), ("send", True, None)])
        path = Path(__file__).parents[1] / "migrations/versions/20260928_0007_infer_historical_outcomes.py"
        spec = importlib.util.spec_from_file_location("outcome_inference_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        await self.conn.run_sync(upgrade)
        rows = (await self.conn.execute(text("SELECT result,reached_top,clean_ascent FROM route_attempts ORDER BY id"))).all()
        self.assertEqual([tuple(row) for row in rows], [
            ("send", True, True), ("send", True, False), ("project", True, False), ("unknown", True, True),
            ("send", True, False), ("send", True, None), ("send", True, True)])
        path = Path(__file__).parents[1] / "migrations/versions/20260928_0008_fix_note_inference.py"
        spec = importlib.util.spec_from_file_location("note_inference_fix_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        await self.conn.run_sync(upgrade)
        rows = (await self.conn.execute(text("SELECT result,reached_top,clean_ascent FROM route_attempts ORDER BY id"))).all()
        self.assertEqual([tuple(row) for row in rows], [
            ("send", True, True), ("send", True, False), ("project", True, False), ("unknown", True, True),
            ("send", True, True), ("send", True, False), ("send", True, True)])
        path = Path(__file__).parents[1] / "migrations/versions/20260929_0009_nonclean_evidence_wins.py"
        spec = importlib.util.spec_from_file_location("nonclean_evidence_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        await self.conn.run_sync(upgrade)
        rows = (await self.conn.execute(text("SELECT result,reached_top,clean_ascent FROM route_attempts ORDER BY id"))).all()
        self.assertEqual([tuple(row) for row in rows], [
            ("send", True, True), ("send", True, False), ("project", True, False), ("unknown", True, True),
            ("send", True, True), ("send", True, False), ("send", True, False)])
        path = Path(__file__).parents[1] / "migrations/versions/20260929_0010_normalize_nonclean_style.py"
        spec = importlib.util.spec_from_file_location("normalize_nonclean_style_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        await self.conn.run_sync(upgrade)
        self.assertEqual(await self.conn.scalar(text("SELECT style FROM route_attempts WHERE id=9")), "unknown")
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

    async def test_past_training_cannot_share_active_route_session(self):
        await self.conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(bind=self.conn, expire_on_commit=False) as session:
            user = {"name": "Past training test"}
            await _start(session, {"user": user, "date": "2026-10-05"})
            await _append(session, {"user": user, "date": "2026-10-05", "name": "R", "cleanAscent": True})
            await _save(session, {"user": user, "date": "2026-10-04", "routes": [{"name": "R", "cleanAscent": False}]})
            count = await session.scalar(text("SELECT count(DISTINCT route_session_key) FROM route_attempts"))
            self.assertEqual(count, 2)

    async def test_ambiguous_summary_is_rejected_without_adding_attempts(self):
        await self.conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(bind=self.conn, expire_on_commit=False) as session:
            user = {"name": "Merge test"}
            await _start(session, {"user": user, "date": "2026-10-05"})
            for clean in (False, True):
                await _append(session, {"user": user, "date": "2026-10-05", "name": "R", "cleanAscent": clean})
            with self.assertRaises(HTTPException) as error:
                async with session.begin_nested():
                    await _save(session, {"user": user, "date": "2026-10-05", "mergeIntoActive": True,
                                         "routes": [{"name": "R", "attempts": 2, "cleanAscent": True}]})
            self.assertEqual(error.exception.status_code, 409)
            self.assertEqual(await session.scalar(text("SELECT sum(attempts) FROM route_attempts")), 2)

    async def test_rest_and_bot_group_attempts_and_obey_test_mode(self):
        await self.conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(bind=self.conn, expire_on_commit=False) as session:
            user = {"name": "REST test"}
            training = await _start(session, {"user": user, "date": "2026-10-05"})
            uid = await session.scalar(text("SELECT id FROM users LIMIT 1"))
            first = await append_attempt(session, uid, training["trainingId"], AttemptCreate(name="R", clean_ascent=False))
            second = await _append(session, {"user": user, "date": "2026-10-05", "name": "R", "cleanAscent": True})
            second_row = await session.get(RouteAttempt, second["attemptId"])
            self.assertEqual(first.route_session_key, second_row.route_session_key)
            self.assertEqual(second_row.attempt_number, 2)
            self.assertEqual(second_row.style, "redpoint")
            person = await session.get(User, uid)
            person.test_mode_enabled = True
            test = await append_attempt(session, uid, training["trainingId"], AttemptCreate(name="R", clean_ascent=True))
            self.assertTrue(test.is_test)
            self.assertNotEqual(test.route_session_key, first.route_session_key)

    async def test_replay_and_payload_conflict_and_deletion_numbering(self):
        await self.conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(bind=self.conn, expire_on_commit=False) as session:
            user = {"name": "Replay test"}
            await execute_tool(session, "start_climbing_training", {"user": user, "date": "2026-10-05"}, "start")
            payload = {"user": user, "date": "2026-10-05", "name": "R", "cleanAscent": False}
            first = await execute_tool(session, "append_climbing_attempt", payload, "one")
            replay = await execute_tool(session, "append_climbing_attempt", payload, "one")
            self.assertEqual(first, replay)
            self.assertEqual(await session.scalar(text("SELECT count(*) FROM route_attempts")), 1)
            with self.assertRaises(HTTPException) as error:
                await execute_tool(session, "append_climbing_attempt", {**payload, "cleanAscent": True}, "one")
            self.assertEqual(error.exception.status_code, 409)
            second = await execute_tool(session, "append_climbing_attempt", payload, "two")
            await execute_tool(session, "append_climbing_attempt", payload, "three")
            await _delete_attempt(session, {"user": user, "attemptId": second["attemptId"]})
            fourth = await execute_tool(session, "append_climbing_attempt", payload, "four")
            self.assertEqual(fourth["number"], 4)

    async def test_rest_replay_returns_original_response_after_finish(self):
        await self.conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(bind=self.conn, expire_on_commit=False) as session:
            user = User(name="REST replay test", test_mode_enabled=True)
            session.add(user)
            await session.flush()
            command = TrainingCreate(date=date(2026, 10, 5))
            first = await start_training_endpoint(command, session, user.id, "start")
            replay = await start_training_endpoint(command, session, user.id, "start")
            self.assertEqual(first, replay)
            attempt = AttemptCreate(name="R", clean_ascent=True)
            added = await append_attempt_endpoint(first["id"], attempt, session, user.id, "append")
            self.assertTrue(added["is_test"])
            await finish_training_endpoint(first["id"], FinishTraining(duration_minutes=60), session, user.id, "finish")
            replay = await append_attempt_endpoint(first["id"], attempt, session, user.id, "append")
            self.assertEqual(added, replay)
            self.assertEqual(await session.scalar(text("SELECT count(*) FROM route_attempts")), 1)
