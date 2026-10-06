"""Authorization contract checks against PostgreSQL; each schema is rolled back."""
import unittest
import importlib.util
from pathlib import Path
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from alembic.migration import MigrationContext
from alembic.operations import Operations

from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import engine, get_session
from app.main import app
from app.models import AuthSession, Base, User


class AuthPostgresTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await engine.connect()
        self.tx = await self.conn.begin()
        schema = "auth_test_" + uuid4().hex
        await self.conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        await self.conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        await self.conn.run_sync(Base.metadata.create_all)
        async def session_override():
            async with AsyncSession(bind=self.conn, expire_on_commit=False,
                                    join_transaction_mode="create_savepoint") as session:
                async with session.begin():
                    yield session
        app.dependency_overrides[get_session] = session_override
        self.settings = patch("app.security.get_settings", return_value=SimpleNamespace(internal_api_key=SecretStr("test-auth-key")))
        self.settings.start()
        self.client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.settings.stop()
        app.dependency_overrides.clear()
        await self.tx.rollback()
        await self.conn.close()
        await engine.dispose()

    async def login(self, telegram_id):
        result = await self.client.post("/api/v1/internal/auth/telegram", json={"telegram_id": telegram_id},
                                        headers={"X-API-Key": "test-auth-key"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers["cache-control"], "no-store")
        return {"Authorization": "Bearer " + result.json()["access_token"]}

    async def tool(self, headers, operation, payload, key=None):
        return await self.client.post("/api/v1/tools/" + operation, json={"payload": payload},
                                      headers={**headers, **({"Idempotency-Key": key} if key else {})})

    async def test_identity_registration_profile_and_session_revocation(self):
        denied = await self.client.post("/api/v1/internal/auth/telegram", json={"telegram_id": "42"})
        self.assertEqual(denied.status_code, 401)
        a, b = await self.login("42"), await self.login("43")
        pa = (await self.client.get("/api/v1/me", headers=a)).json()
        pb = (await self.client.get("/api/v1/me", headers=b)).json()
        self.assertEqual(pa["name"], pb["name"])
        self.assertNotEqual(pa["id"], pb["id"])
        updated = await self.client.patch("/api/v1/me", json={"name":"Антон", "timezone":"Asia/Tbilisi"}, headers=a)
        self.assertEqual(updated.status_code, 200)
        second_login = await self.login("42")
        self.assertEqual((await self.client.get("/api/v1/me", headers=second_login)).json()["name"], "Антон")
        invalid = await self.client.patch("/api/v1/me", json={"timezone":"Not/AZone"}, headers=a)
        self.assertEqual(invalid.status_code, 422)
        spoof = await self.client.get("/api/v1/me", headers={"X-API-Key":"test-auth-key", "X-User-ID":pa["id"]})
        self.assertEqual(spoof.status_code, 401)
        hashes = (await self.conn.execute(text("SELECT token_hash FROM auth_sessions"))).scalars().all()
        self.assertTrue(all(len(h) == 64 and h not in a["Authorization"] for h in hashes))
        self.assertEqual((await self.client.post("/api/v1/auth/logout", headers=a)).status_code, 204)
        self.assertEqual((await self.client.get("/api/v1/me", headers=a)).status_code, 401)
        self.assertEqual((await self.client.get("/api/v1/me", headers=second_login)).status_code, 200)
        await self.client.post("/api/v1/auth/logout-all", headers=second_login)
        self.assertEqual((await self.client.get("/api/v1/me", headers=second_login)).status_code, 401)
        self.assertEqual((await self.client.get("/api/v1/me", headers=b)).status_code, 200)

    async def test_cross_user_reads_writes_statistics_and_idempotency(self):
        a, b = await self.login("100"), await self.login("200")
        uid_b = (await self.client.get("/api/v1/me", headers=b)).json()["id"]
        start_b = await self.tool(b, "start_climbing_training", {})
        tid_b = start_b.json()["trainingId"]
        added = await self.tool(b, "append_climbing_attempt", {"name":"Private B", "cleanAscent":True}, "same-key")
        attempt_b = added.json()["attemptId"]
        gear_b = (await self.tool(b,"upsert_climbing_gear",{"gear":{"type":"shoes","brand":"B"}})).json()["gear"]["id"]
        denied_gear = await self.tool(a,"upsert_climbing_gear",{"gear":{"id":gear_b,"type":"shoes","brand":"attack"}})
        self.assertEqual(denied_gear.status_code, 400)
        denied_link = await self.tool(a,"start_climbing_training",{"gearIds":[gear_b]})
        self.assertEqual(denied_link.status_code, 400)
        for operation, payload in (
            ("update_climbing_attempt", {"attemptId":attempt_b, "notes":"attack"}),
            ("delete_climbing_attempt", {"attemptId":attempt_b}),
            ("update_climbing_training", {"trainingId":tid_b, "notes":"attack"}),
        ):
            result = await self.tool(a, operation, {**payload, "user":{"id":uid_b}})
            self.assertEqual(result.status_code, 404, result.text)
        for path in (f"/api/v1/trainings/{tid_b}/attempts", f"/api/v1/trainings/{tid_b}/finish"):
            result = await self.client.post(path, headers=a, json={})
            self.assertEqual(result.status_code, 404, result.text)
        history = await self.tool(a, "get_climbing_trainings", {"userId":uid_b,"userName":"Скалолаз"})
        self.assertEqual(history.json()["count"], 0)
        stats = await self.tool(a, "get_climbing_statistics", {"user":{"id":uid_b},"scope":"month"})
        self.assertEqual(stats.json()["attemptsCount"], 0)
        own = await self.tool(a, "append_climbing_attempt", {"name":"Private A"}, "same-key")
        self.assertEqual(own.status_code, 200, own.text)
        self.assertNotEqual(own.json()["attemptId"], attempt_b)
        exported = await self.client.get("/api/v1/me/export", headers=a)
        self.assertIn("Private A", exported.text)
        self.assertNotIn("Private B", exported.text)
        self.assertEqual(len((await self.client.get("/api/v1/trainings", headers=a)).json()), 1)

    async def test_expired_blocked_and_deleted_accounts(self):
        a, b = await self.login("501"), await self.login("502")
        uid_a = (await self.client.get("/api/v1/me", headers=a)).json()["id"]
        await self.conn.execute(update(AuthSession).where(AuthSession.user_id == uid_a).values(
            expires_at=datetime.now(UTC)-timedelta(seconds=1)))
        self.assertEqual((await self.client.get("/api/v1/me", headers=a)).status_code, 401)
        a = await self.login("501")
        await self.conn.execute(update(User).where(User.id == uid_a).values(status="blocked"))
        self.assertEqual((await self.client.get("/api/v1/me", headers=a)).status_code, 401)
        denied = await self.client.post("/api/v1/internal/auth/telegram", json={"telegram_id":"501"},headers={"X-API-Key":"test-auth-key"})
        self.assertEqual(denied.status_code, 403)
        await self.conn.execute(update(User).where(User.id == uid_a).values(status="active"))
        gear = await self.tool(a, "upsert_climbing_gear", {"gear":{"type":"shoes","brand":"A"}})
        await self.tool(a, "start_climbing_training", {"gearIds":[gear.json()["gear"]["id"]]})
        await self.tool(a, "append_climbing_attempt", {"name":"A"})
        self.assertEqual((await self.client.delete("/api/v1/me", headers=a)).status_code, 204)
        self.assertEqual((await self.client.get("/api/v1/me", headers=a)).status_code, 401)
        self.assertEqual((await self.client.get("/api/v1/me", headers=b)).status_code, 200)
        for table in ("training_sessions", "gear", "auth_sessions", "external_refs"):
            count = await self.conn.scalar(text(f"SELECT count(*) FROM {table} WHERE user_id=:uid"), {"uid":uid_a})
            self.assertEqual(count, 0)

    async def test_migration_preserves_existing_telegram_identity(self):
        headers = await self.login("601")
        profile = (await self.client.get("/api/v1/me",headers=headers)).json()
        await self.conn.execute(text("DROP TABLE auth_sessions"))
        await self.conn.execute(text("ALTER TABLE users DROP CONSTRAINT ck_user_status"))
        await self.conn.execute(text("ALTER TABLE users DROP COLUMN status"))
        path = Path(__file__).parents[1] / "migrations/versions/20261005_0011_user_auth.py"
        spec = importlib.util.spec_from_file_location("auth_migration",path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        def upgrade(conn):
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        await self.conn.run_sync(upgrade)
        headers = await self.login("601")
        self.assertEqual((await self.client.get("/api/v1/me",headers=headers)).json(),profile)
