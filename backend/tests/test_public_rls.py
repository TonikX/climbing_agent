"""Apply real migrations and query as a non-owner role; every change rolls back."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import engine


class RowSecurityTest(unittest.IsolatedAsyncioTestCase):
    async def test_migration_preserves_ids_and_runtime_fails_closed(self):
        async with engine.connect() as conn:
            tx = await conn.begin()
            schema = "rls_test_" + uuid4().hex
            role = "rls_role_" + uuid4().hex
            try:
                await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                if not await conn.scalar(text("SELECT EXISTS(SELECT FROM pg_roles WHERE rolname='climbing_control')")):
                    await conn.execute(text("CREATE ROLE climbing_control NOLOGIN NOBYPASSRLS NOSUPERUSER"))
                directory = Path(__file__).parents[1] / "migrations/versions"
                files = sorted(directory.glob("*.py"))
                async def migrate(path):
                    spec = importlib.util.spec_from_file_location("migration_" + path.stem, path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    def apply(sync):
                        with Operations.context(MigrationContext.configure(sync)):
                            module.upgrade()
                    await conn.run_sync(apply)
                for path in files[:-1]:
                    await migrate(path)
                await conn.execute(text("INSERT INTO users(id,name,timezone) VALUES ('a','A','Europe/Moscow'),('b','B','Europe/Moscow')"))
                await conn.execute(text("INSERT INTO locations(id,type,name) VALUES ('loc','outdoor','Private A')"))
                await conn.execute(text("""INSERT INTO training_sessions(id,user_id,status,local_date,timezone,environment,version)
                    VALUES ('ta','a','active','2026-10-10','Europe/Moscow','unknown',1),
                           ('tb','b','active','2026-10-10','Europe/Moscow','unknown',1)"""))
                await conn.execute(text("""INSERT INTO route_attempts(id,training_id,sequence,attempts,result,style,belay,feel,route_snapshot)
                    VALUES ('aa','ta',1,1,'unknown','unknown','unknown','unknown','{"name":"A","grade":"6B/6B+"}'),
                           ('ab','tb',1,1,'unknown','unknown','unknown','unknown','{"name":"B"}')"""))
                before = list((await conn.execute(text("SELECT id,route_snapshot FROM route_attempts ORDER BY id"))).all())
                with patch.dict("os.environ", {"PUBLIC_MIGRATION_MANIFEST": json.dumps({"approved_user_ids": ["a"], "location_owners": {"loc": "a"}})}):
                    await migrate(files[-1])
                self.assertEqual(before, list((await conn.execute(text("SELECT id,route_snapshot FROM route_attempts ORDER BY id"))).all()))
                self.assertEqual(await conn.scalar(text("SELECT status FROM users WHERE id='b'")), "pending_approval")
                await conn.execute(text(f'CREATE ROLE "{role}" NOLOGIN NOSUPERUSER NOBYPASSRLS'))
                await conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
                await conn.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
                await conn.execute(text(f'GRANT INSERT,UPDATE,DELETE ON training_sessions,route_attempts,gear,locations,sections,routes,training_gear,training_sections,idempotency_keys TO "{role}"'))
                await conn.execute(text(f'GRANT UPDATE(name,timezone,test_mode_enabled) ON users TO "{role}"'))
                await conn.execute(text(f'SET LOCAL ROLE "{role}"'))
                self.assertEqual(await conn.scalar(text("SELECT count(*) FROM training_sessions")), 0)
                await conn.execute(text("SELECT set_config('app.user_id','a',true)"))
                self.assertEqual(list((await conn.execute(text("SELECT id FROM route_attempts"))).scalars()), ["aa"])
                self.assertEqual(await conn.scalar(text("SELECT count(*) FROM locations")), 1)
                self.assertEqual(await conn.scalar(text("SELECT count(*) FROM jobs")), 0)
                async with conn.begin_nested() as savepoint:
                    with self.assertRaises(DBAPIError):
                        await conn.execute(text("""INSERT INTO route_attempts(id,training_id,sequence,attempts,result,style,belay,feel,route_snapshot)
                            VALUES ('attack','tb',2,1,'unknown','unknown','unknown','unknown','{}')"""))
                    await savepoint.rollback()
                await conn.execute(text("SELECT set_config('app.user_id','b',true)"))
                self.assertEqual(await conn.scalar(text("SELECT count(*) FROM route_attempts")), 0)
                async with conn.begin_nested() as savepoint:
                    with self.assertRaises(DBAPIError):
                        await conn.execute(text("UPDATE users SET status='active' WHERE id='b'"))
                    await savepoint.rollback()
                await conn.execute(text("RESET ROLE"))
                await conn.execute(text("UPDATE users SET status='active' WHERE id='b'"))
                await conn.execute(text(f'SET LOCAL ROLE "{role}"'))
                self.assertEqual(list((await conn.execute(text("SELECT id FROM route_attempts"))).scalars()), ["ab"])
                self.assertEqual(await conn.scalar(text("SELECT count(*) FROM locations")), 0)
                await conn.execute(text("SELECT set_config('app.user_id','',true)"))
                self.assertEqual(await conn.scalar(text("SELECT count(*) FROM route_attempts")), 0)
            finally:
                await tx.rollback()
        await engine.dispose()
