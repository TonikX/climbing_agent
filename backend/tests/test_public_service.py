"""Acceptance boundaries: admission, durable retries and stale AI work."""
import unittest
from unittest.mock import patch

from sqlalchemy import func, select, update

from app.config import get_settings
from app.models import RouteAttempt, User
from app.public_models import AccessRequest, Job, Outbox, TelegramUpdate
from app.public_schemas import Intent
import test_auth_postgres as auth_tests


class PublicServiceTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUpBase = auth_tests.AuthPostgresTest.asyncSetUp
    asyncTearDownBase = auth_tests.AuthPostgresTest.asyncTearDown
    login = auth_tests.AuthPostgresTest.login

    async def asyncSetUp(self):
        await self.asyncSetUpBase()
        cfg = get_settings().model_copy(update={"access_approver_telegram_id": "1", "access_approval_chat_id": "1",
            "ai_daily_budget_units": 10, "ai_call_reservation_units": 1, "telegram_bot_id": "123"})
        self.patches = [patch(module+".get_settings", return_value=cfg) for module in ("app.access", "app.jobs", "app.telegram_actions")]
        for item in self.patches:
            item.start()
        self.n = 0

    async def asyncTearDown(self):
        for item in self.patches:
            item.stop()
        await self.asyncTearDownBase()

    async def send(self, tid, text, callback=False, update_id=None, forwarded=False):
        self.n += 1
        raw = {"update_id": update_id or self.n}
        actor = {"id": int(tid), "is_bot": False, "first_name": "Same name"}
        message = {"message_id": self.n, "date": 1790000000, "chat": {"id": int(tid), "type": "private"}, "from": actor, "text": text}
        if callback:
            message["from"] = {"id": 123, "is_bot": True, "first_name": "Journal"}
            if text.startswith(("approve:", "reject:")):
                await self.deliver_all()
                card_id = await self.conn.scalar(select(Outbox.telegram_message_id).where(
                    Outbox.access_request_id == text.split(":", 1)[1], Outbox.status == "succeeded"))
                message["message_id"] = card_id or self.n
            if forwarded:
                message["forward_origin"] = {"type": "user", "date": 1790000000, "sender_user": actor}
            raw["callback_query"] = {"id": str(self.n), "from": actor, "chat_instance": "test", "message": message, "data": text}
        else:
            raw["message"] = message
        result = await self.client.post("/api/v1/internal/telegram/updates", json=raw, headers={"X-API-Key": "test-auth-key"})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    async def deliver_all(self):
        headers = {"X-API-Key": "test-auth-key"}
        index = 100
        while True:
            response = await self.client.post("/api/v1/internal/jobs/claim", headers=headers,
                json={"worker_id": "delivery", "lane": "delivery"})
            self.assertEqual(response.status_code, 200, response.text)
            item = response.json()["item"]
            if not item:
                return
            index += 1
            done = await self.client.post(f"/api/v1/internal/jobs/delivery/{item['id']}/complete", headers=headers,
                json={"worker_id": "delivery", "telegram_message_id": index})
            self.assertEqual(done.status_code, 200, done.text)

    async def process(self, lane="fast", intent=None):
        headers = {"X-API-Key": "test-auth-key"}
        result = await self.client.post("/api/v1/internal/jobs/claim", json={"worker_id": "worker", "lane": lane}, headers=headers)
        self.assertEqual(result.status_code, 200, result.text)
        item = result.json()["item"]
        if not item:
            return None
        payload = {"worker_id": "worker"}
        if intent:
            payload["intent"] = intent.model_dump(mode="json")
        complete = await self.client.post(f"/api/v1/internal/jobs/{lane}/{item['id']}/complete", json=payload, headers=headers)
        self.assertEqual(complete.status_code, 200, complete.text)
        return item

    async def test_pending_account_cannot_read_or_spend_and_owner_decides_once(self):
        await self.login("1")
        await self.conn.execute(update(User).values(role="admin"))
        first = await self.send("2", "/start")
        await self.process()
        duplicate = await self.send("2", "/start", update_id=1)
        self.assertTrue(duplicate["duplicate"])
        denied = await self.client.post("/api/v1/internal/auth/telegram", json={"telegram_id": "2"}, headers={"X-API-Key": "test-auth-key"})
        self.assertEqual(denied.status_code, 403)
        await self.send("2", "stats:month", True)
        await self.process()
        await self.send("2", "Запиши пролаз 7A")
        await self.process()
        self.assertEqual(await self.conn.scalar(select(func.count(Job.id)).where(Job.lane == "ai")), 0)
        await self.send("2", "access:request", True)
        await self.process()
        request_id = await self.conn.scalar(select(AccessRequest.id))
        self.assertTrue(request_id)
        await self.send("2", "access:request", True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(func.count(AccessRequest.id))), 1)
        await self.send("2", "approve:"+request_id, True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(AccessRequest.status)), "pending")
        await self.send("1", "approve:"+request_id, True, forwarded=True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(AccessRequest.status)), "pending")
        await self.send("1", "approve:"+request_id, True)
        await self.process()
        await self.send("1", "reject:"+request_id, True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(AccessRequest.status)), "approved")
        login = await self.client.post("/api/v1/internal/auth/telegram", json={"telegram_id": "2"}, headers={"X-API-Key": "test-auth-key"})
        self.assertEqual(login.status_code, 200, login.text)

    async def test_stale_ai_cannot_write_to_next_training(self):
        await self.login("2")
        await self.send("2", "training:start", True)
        await self.process()
        await self.send("2", "Трасса 6B флеш")
        headers = {"X-API-Key": "test-auth-key"}
        ai = (await self.client.post("/api/v1/internal/jobs/claim", json={"worker_id": "ai", "lane": "ai"}, headers=headers)).json()["item"]
        self.assertTrue(ai)
        await self.send("2", "stats:week", True)
        self.assertTrue(await self.process())  # Statistics bypass the blocked mutation lane.
        await self.send("2", "training:finish:cancel", True)
        await self.process()
        await self.send("2", "training:start", True)
        await self.process()
        late = await self.client.post(f"/api/v1/internal/jobs/ai/{ai['id']}/complete", headers=headers,
            json={"worker_id": "ai", "intent": Intent(kind="attempt", name="Трасса", grade="6B", style="flash").model_dump(mode="json")})
        self.assertEqual(late.status_code, 409)
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)

    async def test_attempt_commits_once_and_delivery_failure_does_not_repeat_it(self):
        await self.login("2")
        await self.send("2", "training:start", True)
        await self.process()
        await self.send("2", "Трасса 6B флеш, один срыв")
        item = await self.process("ai", Intent(kind="attempt", name="Трасса", grade="6B", style="flash", falls=1, reached_top=True))
        rows = (await self.conn.execute(select(RouteAttempt))).all()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].clean_ascent)
        self.assertEqual(rows[0].style, "unknown")
        retry = await self.client.post(f"/api/v1/internal/jobs/ai/{item['id']}/complete", headers={"X-API-Key": "test-auth-key"},
             json={"worker_id": "worker", "intent": Intent(kind="attempt", name="Трасса", grade="6B").model_dump(mode="json")})
        self.assertEqual(retry.status_code, 409)
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 1)

    async def test_private_catalogue_and_source_ids_cannot_leak(self):
        a, b = await self.login("2"), await self.login("3")
        created = await self.client.post("/api/v1/catalog/locations", json={"name": "Private place"}, headers=a)
        self.assertEqual(created.status_code, 200, created.text)
        location_id = created.json()["id"]
        self.assertNotIn("Private place", (await self.client.get("/api/v1/catalog/locations", headers=b)).text)
        foreign = await self.client.post("/api/v1/catalog/sections", json={"location_id": location_id, "name": "Attack"}, headers=b)
        self.assertEqual(foreign.status_code, 404, foreign.text)
        spoof = await self.client.post("/api/v1/catalog/locations", json={"name": "Attack", "externalRefs": [{"system": "allclimb", "id": "42"}]}, headers=b)
        self.assertEqual(spoof.status_code, 422)

    async def test_manual_form_without_ai_and_deletion_cancels_old_work(self):
        a, b = await self.login("2"), await self.login("3")
        for text, callback in (("training:start", True), ("attempt:form", True), ("Трасса", False), ("6B", False),
            ("form:top_rope", True), ("form:yes", True), ("form:flash", True), ("form:yes", True), ("0", False), ("1", False)):
            await self.send("2", text, callback)
            await self.process()
        attempt = (await self.conn.execute(select(RouteAttempt))).one()
        self.assertFalse(attempt.clean_ascent)
        self.assertEqual(attempt.hangs, 1)
        self.assertEqual(attempt.belay, "top_rope")
        self.assertEqual(await self.conn.scalar(select(func.count(Job.id)).where(Job.lane == "ai")), 0)
        queued = await self.send("2", "Ещё попытка на трассе 6B")
        confirmation = (await self.client.post("/api/v1/account-deletion", headers=a)).json()["confirmation"]
        stolen = await self.client.delete("/api/v1/me", headers=b, params={"confirmation": confirmation})
        self.assertEqual(stolen.status_code, 409)
        deleted = await self.client.delete("/api/v1/me", headers=a, params={"confirmation": confirmation})
        self.assertEqual(deleted.status_code, 204, deleted.text)
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)
        replay = await self.send("2", "Replay", update_id=self.n)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(await self.conn.scalar(select(func.count(User.id))), 1)
