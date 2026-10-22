"""Acceptance boundaries: admission, durable retries and stale AI work."""
import unittest
from unittest.mock import patch

from sqlalchemy import func, select, update

from app.config import get_settings
from app.models import RouteAttempt, TrainingSession, User
from app.public_models import AccessRequest, Job, Outbox, TelegramUpdate
from app.public_models import DialogState
from app.public_schemas import Intent
import test_auth_postgres as auth_tests


def record_intent(**values):
    facts = {"kind": "attempt", "region": "Test region", "sector": "Test sector",
             "belay": "top_rope", "style": "with_hangs"}
    facts.update(values)
    return Intent(**facts)


class PublicServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_change_training_date_buttons_validation_and_ownership(self):
        from datetime import date
        await self.login('2')
        await self.login('3')
        await self.send('2', 'training:start', True)
        await self.process()
        await self.send('2', 'Трасса 6A')
        await self.process('ai', record_intent(name='Трасса', grade='6A'))
        ai_count = await self.conn.scalar(select(func.count(Job.id)).where(Job.lane=='ai'))
        tid, version, original = (await self.conn.execute(select(TrainingSession.id, TrainingSession.version, TrainingSession.local_date))).one()
        await self.send('2', 'training:details:current', True)
        await self.process()
        payload = await self.conn.scalar(select(Outbox.payload).order_by(Outbox.sequence.desc()).limit(1))
        command = f'td:{tid}:{version}'
        self.assertTrue(any(b['callback_data']==command for row in payload['reply_markup']['inline_keyboard'] for b in row))
        await self.send('3', command, True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(TrainingSession.local_date)), original)
        await self.send('2', command, True)
        await self.process()
        await self.send('2', '31.02.2026')
        await self.process()
        self.assertEqual(await self.conn.scalar(select(TrainingSession.local_date)), original)
        self.assertEqual(await self.conn.scalar(select(DialogState.state)), 'training_date')
        await self.send('2', '01.09.2026')
        await self.process()
        self.assertEqual(await self.conn.scalar(select(TrainingSession.local_date)), date(2026,9,1))
        # An old button must not overwrite a newer version.
        await self.send('2', command, True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(DialogState.state)), 'training_selected')
        await self.send('2', 'training:finish', True)
        await self.process()
        before = (await self.conn.execute(select(TrainingSession.status, TrainingSession.started_at, TrainingSession.completed_at, TrainingSession.duration_minutes))).one()
        version = await self.conn.scalar(select(TrainingSession.version))
        await self.send('2', 'tr:'+tid, True)
        await self.process()
        payload = await self.conn.scalar(select(Outbox.payload).order_by(Outbox.sequence.desc()).limit(1))
        command = f'td:{tid}:{version}'
        self.assertTrue(any(b['callback_data']==command for row in payload['reply_markup']['inline_keyboard'] for b in row))
        await self.send('2', command, True)
        await self.process()
        await self.send('2', '2026-08-31')
        await self.process()
        self.assertEqual(await self.conn.scalar(select(TrainingSession.local_date)), date(2026,8,31))
        after = (await self.conn.execute(select(TrainingSession.status, TrainingSession.started_at, TrainingSession.completed_at, TrainingSession.duration_minutes))).one()
        self.assertEqual(before, after)
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 1)
        self.assertEqual(await self.conn.scalar(select(func.count(Job.id)).where(Job.lane=='ai')), ai_count)

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

    async def send(self, tid, text, callback=False, update_id=None, forwarded=False, voice=False):
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
            if voice:
                message.pop("text")
                message["voice"] = {"file_id": "test", "file_unique_id": "test", "duration": 2}
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
        # Existing journal scenarios explicitly approve new catalogue entries.
        # Catalogue-specific tests disable this helper and inspect every choice.
        if getattr(self, "approve_new_catalog", True):
            draft = await self.conn.scalar(select(DialogState.data).where(DialogState.state=="catalog_choice"))
            selection = (draft or {}).get("selection", {})
            if selection.get("query") and selection.get("field") != "grade":
                await self.send(item["payload"]["telegram_id"], "cn:"+selection["token"], True)
                await self.process()
            elif selection.get("field") == "grade":
                await self.send(item["payload"]["telegram_id"], "cg:"+selection["token"]+":user", True)
                await self.process()
        return item

    async def confirm_attempt_deletion(self):
        data=await self.conn.scalar(select(DialogState.data).where(DialogState.state=="attempt_delete"))
        await self.send("2", "am:delete:"+data["confirmation"], True)
        await self.process()

    async def start_at_test_location(self, headers):
        area = (await self.client.post("/api/v1/catalog/locations", headers=headers, json={"name":"Test region"})).json()
        sector = (await self.client.post("/api/v1/catalog/sections", headers=headers,
            json={"location_id":area["id"],"name":"Test sector"})).json()
        result = await self.client.post("/api/v1/trainings", headers=headers,
            json={"date":"2026-10-15","location_id":area["id"],"section_id":sector["id"]})
        self.assertEqual(result.status_code,201,result.text)

    async def test_resume_last_training_ui_and_rest_guards(self):
        headers = await self.login("2")
        other = await self.login("3")
        created = await self.client.post("/api/v1/trainings", headers=headers, json={"date":"2026-10-15", "notes":"keep"})
        tid = created.json()["id"]
        added = await self.client.post(f"/api/v1/trainings/{tid}/attempts", headers=headers,
            json={"name":"Resume route", "grade":"6A", "reached_top":False})
        self.assertEqual(added.status_code, 201, added.text)
        finished = await self.client.post(f"/api/v1/trainings/{tid}/finish", headers=headers, json={"duration_minutes":30})
        version = finished.json()["version"]
        foreign = await self.client.post(f"/api/v1/trainings/{tid}/resume", headers=other, json={"expected_version":version})
        self.assertEqual(foreign.status_code, 404)
        stale = await self.client.post(f"/api/v1/trainings/{tid}/resume", headers=headers, json={"expected_version":version-1})
        self.assertEqual(stale.status_code, 409)
        await self.send("2", "↩️ Возобновить последнюю тренировку")
        await self.process()
        prompt = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        self.assertIn("15.10.2026", prompt["text"])
        self.assertEqual(await self.conn.scalar(select(TrainingSession.status).where(TrainingSession.id==tid)), "completed")
        await self.send("2", f"rs:{tid}:{version}", True)
        await self.process()
        row = (await self.conn.execute(select(TrainingSession.status, TrainingSession.version,
            TrainingSession.completed_at, TrainingSession.duration_minutes, TrainingSession.notes).where(TrainingSession.id==tid))).one()
        self.assertEqual(tuple(row), ("active", version+1, None, None, "keep"))
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),1)
        await self.send("2", f"rs:{tid}:{version}", True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(TrainingSession.version).where(TrainingSession.id==tid)),version+1)
        self.assertEqual((await self.client.post("/api/v1/trainings", headers=headers, json={"date":"2026-10-15"})).status_code,409)
        finished = await self.client.post(f"/api/v1/trainings/{tid}/finish", headers=headers,json={})
        version = finished.json()["version"]
        newer = await self.client.post("/api/v1/trainings", headers=headers, json={"date":"2026-10-16"})
        self.assertEqual((await self.client.post(f"/api/v1/trainings/{tid}/resume", headers=headers,json={"expected_version":version})).status_code,409)
        await self.client.post(f"/api/v1/trainings/{newer.json()['id']}/finish", headers=headers,json={})
        self.assertEqual((await self.client.post(f"/api/v1/trainings/{tid}/resume", headers=headers,json={"expected_version":version})).status_code,409)
        new_tid = newer.json()["id"]
        new_version = await self.conn.scalar(select(TrainingSession.version).where(TrainingSession.id==new_tid))
        replay_headers={**headers,"Idempotency-Key":"resume-once"}
        for _ in range(2):
            resumed = await self.client.post(f"/api/v1/trainings/{new_tid}/resume", headers=replay_headers,json={"expected_version":new_version})
            self.assertEqual(resumed.status_code,200,resumed.text)
            self.assertEqual(resumed.json()["version"],new_version+1)

    async def test_first_attempt_draft_voice_clarification_and_current_screen(self):
        from app.models import Location, Section
        from aiogram.types import ReplyKeyboardMarkup, InlineKeyboardMarkup
        await self.login("2")
        await self.send("2", "Начать тренировку")
        await self.process()
        await self.send("2", "Гейкбаири, Кебап, Engesh 6a")
        await self.process("ai", Intent(kind="attempt", region="Гейкбаири", sector="Кебап", name="Engesh", grade="6a", attempts=3))
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)
        prompt = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        self.assertIn("Чисто", prompt["text"])
        self.assertIn("Страховка", prompt["text"])
        self.assertNotIn("• Регион", prompt["text"])
        await self.send("2", "🧗 Текущая тренировка")
        await self.process()
        self.assertEqual(await self.conn.scalar(select(DialogState.state)), "attempt_missing")
        await self.send("2", "", voice=True)
        item = await self.process("ai", Intent(kind="attempt", style="with_hangs", belay="lead", reached_top=True, hangs=1))
        self.assertEqual(item["payload"]["pending_attempt"]["facts"]["name"], "Engesh")
        row = (await self.conn.execute(select(RouteAttempt.route_snapshot, RouteAttempt.clean_ascent, RouteAttempt.style, RouteAttempt.belay, RouteAttempt.attempts))).one()
        self.assertFalse(row.clean_ascent)
        self.assertEqual((row.style, row.belay, row.attempts), ("with_hangs", "lead", 3))
        self.assertEqual(await self.conn.scalar(select(Location.name).where(Location.id==row.route_snapshot["areaId"])), "Гейкбаири")
        self.assertEqual(await self.conn.scalar(select(Section.name).where(Section.id==row.route_snapshot["sectorId"])), "Кебап")
        self.assertEqual(await self.conn.scalar(select(func.count(DialogState.user_id))), 0)
        await self.send("2", "🧗 Текущая тренировка")
        await self.process()
        screen = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        self.assertIn("Engesh", screen["text"])
        self.assertIn("Гейкбаири", screen["text"])
        markup = InlineKeyboardMarkup.model_validate(screen["reply_markup"])
        self.assertTrue(any(x.callback_data.startswith("am:pick:") for row in markup.inline_keyboard for x in row))
        self.assertTrue(any(x.callback_data=="training:location" for row in markup.inline_keyboard for x in row))
        await self.send("2", "🏠 Главное меню")
        await self.process()
        payload = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        markup = ReplyKeyboardMarkup.model_validate(payload["reply_markup"])
        labels = [x.text for row in markup.keyboard for x in row]
        self.assertIn("🧗 Текущая тренировка", labels)
        self.assertIn("🏠 Главное меню", labels)
        self.assertNotIn("📋 Все попытки", labels)
        ai_before = await self.conn.scalar(select(func.count(Job.id)).where(Job.lane=="ai"))
        await self.send("2", "📊 Статистика")
        await self.process()
        self.assertEqual(await self.conn.scalar(select(func.count(Job.id)).where(Job.lane=="ai")), ai_before)
        await self.send("2", "Другая 6b flash, верхняя")
        await self.process("ai", Intent(kind="attempt", name="Другая", grade="6b", style="flash", belay="top_rope"))
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 2)
        inherited = await self.conn.scalar(select(RouteAttempt.route_snapshot).order_by(RouteAttempt.sequence.desc()).limit(1))
        self.assertEqual((inherited["areaId"], inherited["sectorId"]), (row.route_snapshot["areaId"], row.route_snapshot["sectorId"]))
        aid = await self.conn.scalar(select(RouteAttempt.id).order_by(RouteAttempt.sequence.desc()).limit(1))
        await self.send("2", "am:pick:"+aid, True)
        await self.process()
        editor = (await self.conn.scalar(select(DialogState.data)))["editor_token"]
        await self.send("2", "am:field:"+editor+":region", True)
        await self.process()
        await self.send("2", "🧪 Тестовый режим")
        await self.process()
        self.assertEqual(await self.conn.scalar(select(RouteAttempt.route_snapshot).where(RouteAttempt.id==aid)), inherited)
        await self.send("2", "🏠 Главное меню")
        await self.process()
        self.assertEqual(await self.conn.scalar(select(RouteAttempt.route_snapshot).where(RouteAttempt.id==aid)), inherited)

    async def test_draft_cancel_invalidates_inflight_answer(self):
        await self.login("2")
        await self.send("2", "training:start", True)
        await self.process()
        await self.send("2", "Engesh 6a")
        await self.process("ai", Intent(kind="attempt", name="Engesh", grade="6a"))
        await self.send("2", "Гейкбаири, Кебап, flash, нижняя")
        headers = {"X-API-Key": "test-auth-key"}
        item = (await self.client.post("/api/v1/internal/jobs/claim", headers=headers,
            json={"worker_id":"ai", "lane":"ai"})).json()["item"]
        self.assertTrue(item["payload"]["pending_attempt"])
        await self.send("2", "/cancel")
        self.assertTrue(await self.process())
        result = await self.client.post(f"/api/v1/internal/jobs/ai/{item['id']}/complete", headers=headers,
            json={"worker_id":"ai", "intent":Intent(kind="attempt", region="Гейкбаири", sector="Кебап", style="flash", belay="lead").model_dump(mode="json",exclude_none=True)})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)

    async def test_test_only_trainings_hidden_and_mixed_training_statistics_use_real_attempts(self):
        headers = await self.login("2")
        ids = []
        for name, grade, is_test in (("Только тест", "9C", True), ("Реальная", "5A", False)):
            await self.send("2", "training:start", True)
            await self.process()
            await self.send("2", name)
            await self.process("ai", record_intent(name=name, grade=grade, style="flash", reached_top=True, is_test=is_test))
            ids.append(await self.conn.scalar(select(TrainingSession.id).where(TrainingSession.status=="active")))
            if not is_test:
                await self.send("2", "Тест в смешанной")
                await self.process("ai", record_intent(name="Тест в смешанной", grade="8C", style="flash", reached_top=True, is_test=True))
            await self.send("2", "training:finish", True)
            await self.process()
        normal = await self.client.get("/api/v1/trainings", headers=headers)
        self.assertEqual(normal.status_code, 200, normal.text)
        self.assertEqual([x["id"] for x in normal.json()["items"]], [ids[1]])
        self.assertEqual(len(normal.json()["items"][0]["attempts"]), 1)
        all_data = await self.client.get("/api/v1/trainings?include_test=true", headers=headers)
        self.assertEqual(len(all_data.json()["items"]), 2)
        history = await self.client.post("/api/v1/tools/get_climbing_trainings", headers=headers, json={"payload":{}})
        self.assertEqual(history.status_code, 200, history.text)
        self.assertEqual([x["id"] for x in history.json()["trainings"]], [ids[1]])
        for scope in ("month", "week", "grades", "locations", "projects", "progress", "records"):
            response = await self.client.get("/api/v1/statistics/"+scope, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["trainingsCount"], 1)
            self.assertEqual(response.json()["attemptsCount"], 1)
            self.assertEqual(response.json()["maxAttemptedGrade"], "5A")
        await self.send("2", "trainings:0", True)
        await self.process()
        payload = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        buttons = [x["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for x in row]
        self.assertNotIn("tr:"+ids[0], buttons)
        self.assertIn("tr:"+ids[1], buttons)
        self.assertIn("trainings-test:0", buttons)
        await self.send("2", "trainings-test:0", True)
        await self.process()
        payload = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        buttons = [x["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for x in row]
        self.assertIn("tr:"+ids[0], buttons)
        await self.send("2", "training:start", True)
        await self.process()
        await self.send("2", "Тест текущей")
        await self.process("ai", record_intent(name="Тест текущей", grade="9C", is_test=True))
        current = await self.client.get("/api/v1/statistics/current-training", headers=headers)
        self.assertFalse(current.json()["active"])
        await self.send("2", "stats:current", True)
        await self.process()
        payload = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        self.assertNotIn("training:details:current", [x["callback_data"] for row in payload["reply_markup"]["inline_keyboard"] for x in row])
        await self.send("2", "training:details:current", True)
        await self.process()
        payload = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        self.assertIn("Тест текущей", payload["text"])

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

    async def test_upper_style_manual_ai_editor_and_statistics_keep_cleanliness_independent(self):
        headers = await self.login("2")
        await self.start_at_test_location(headers)
        for value, callback in (("attempt:form", True), ("Верхняя трасса", False), ("6B", False),
            ("form:top_rope", True), ("form:yes", True), ("form:top_rope", True), ("form:yes", True), ("0", False), ("1", False)):
            await self.send("2", value, callback)
            await self.process()
        saved = (await self.conn.execute(select(RouteAttempt.id, RouteAttempt.style, RouteAttempt.clean_ascent, RouteAttempt.belay))).one()
        self.assertEqual((saved.style, saved.clean_ascent, saved.belay), ("top_rope", False, "top_rope"))
        await self.send("2", "Вторая, верхняя, чисто")
        await self.process("ai", record_intent(name="Вторая", grade="6A", style="top_rope", clean_ascent=True, falls=0, hangs=0))
        await self.send("2", "Тестовая верхняя")
        await self.process("ai", record_intent(name="Тестовая верхняя", grade="9C", style="top_rope", clean_ascent=True, falls=1, is_test=True))
        stats = await self.client.get("/api/v1/statistics/month", headers=headers)
        self.assertEqual(stats.status_code, 200, stats.text)
        self.assertEqual(stats.json()["topRopeStyleAttemptsCount"], 2)
        self.assertEqual(stats.json()["completedRoutes"], 1)
        await self.send("2", "am:pick:"+saved.id, True)
        await self.process()
        editor = (await self.conn.scalar(select(DialogState.data)))["editor_token"]
        await self.send("2", "am:field:"+editor+":style", True)
        await self.process()
        data = await self.conn.scalar(select(DialogState.data))
        payload = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        self.assertTrue(any(x["text"]=="Верхняя" for row in payload["reply_markup"]["inline_keyboard"] for x in row))
        await self.send("2", "am:value:"+data["value_token"]+":top_rope", True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(RouteAttempt.style).where(RouteAttempt.id==saved.id)), "top_rope")
        self.assertFalse(await self.conn.scalar(select(RouteAttempt.clean_ascent).where(RouteAttempt.id==saved.id)))

    async def test_ai_entry_exits_manual_form_and_saves_interpreted_attempt(self):
        await self.login("2")
        await self.send("2", "training:start", True)
        await self.process()
        await self.send("2", "attempt:form", True)
        await self.process()
        await self.send("2", "attempt:ai", True)
        await self.process()
        await self.send("2", "Трасса 6B, верхняя страховка, долез с зависанием")
        self.assertEqual(await self.conn.scalar(select(Job.lane).order_by(Job.sequence.desc()).limit(1)), "ai")
        await self.process("ai", record_intent(name="Трасса", grade="6B", reached_top=True,
                                       clean_ascent=True, hangs=1, belay="top_rope"))
        saved = (await self.conn.execute(select(RouteAttempt.reached_top, RouteAttempt.clean_ascent,
                                               RouteAttempt.hangs, RouteAttempt.belay))).one()
        self.assertTrue(saved.reached_top)
        self.assertFalse(saved.clean_ascent)
        self.assertEqual(saved.hangs, 1)
        self.assertEqual(saved.belay, "top_rope")
        await self.send("2", "stats:month", True)
        self.assertEqual(await self.conn.scalar(select(Job.lane).order_by(Job.sequence.desc()).limit(1)), "fast")
        await self.process()

    async def test_defaults_bulk_edit_button_edit_and_confirmed_deletion(self):
        from app.public_schemas import AttemptChanges
        await self.login("2")
        await self.send("2", "training:start", True)
        await self.process()
        for name in ("Первая", "Вторая"):
            await self.send("2", f"{name} 6A")
            await self.process("ai", record_intent(name=name, grade="6A"))
        initial = (await self.conn.execute(select(RouteAttempt.id, RouteAttempt.training_id, RouteAttempt.clean_ascent,
            RouteAttempt.belay).order_by(RouteAttempt.sequence))).all()
        self.assertEqual([(x.clean_ascent, x.belay) for x in initial], [(False,"top_rope")]*2)
        await self.send("2", "training:finish", True)
        await self.process()
        await self.send("2", "В последней тренировке все пролазы с зависанием, нижняя страховка")
        await self.process("ai", Intent(kind="update_attempts", training_scope="last", target_all=True,
            changes=AttemptChanges(style="with_hangs", belay="lead")))
        values=(await self.conn.execute(select(RouteAttempt.clean_ascent,RouteAttempt.style,RouteAttempt.belay))).all()
        self.assertEqual([(x.clean_ascent,x.style,x.belay) for x in values],[(False,"with_hangs","lead")]*2)
        await self.send("2", "am:pick:"+initial[0].id, True)
        await self.process()
        editor=(await self.conn.scalar(select(DialogState.data).where(DialogState.state=="attempt_edit")))["editor_token"]
        await self.send("2", "am:field:"+editor+":grade", True)
        await self.process()
        await self.send("2", "6B+")
        await self.process()
        self.assertEqual((await self.conn.scalar(select(RouteAttempt.route_snapshot).where(RouteAttempt.id==initial[0].id)))["grade"],"6B+")
        await self.send("2", "training:start", True)
        await self.process()
        await self.send("2", "Третья 6B со срывом")
        await self.process("ai", record_intent(name="Третья",grade="6B",falls=1))
        current_id=await self.conn.scalar(select(RouteAttempt.id).where(RouteAttempt.route_snapshot["name"].astext=="Третья"))
        await self.send("2", "Удали пролаз Третья текущей тренировки")
        await self.process("ai", Intent(kind="delete_attempts",training_scope="current",target_name="Третья"))
        self.assertIsNotNone(await self.conn.scalar(select(RouteAttempt.id).where(RouteAttempt.id==current_id)))
        old_confirmation=(await self.conn.scalar(select(DialogState.data).where(DialogState.state=="attempt_delete")))["confirmation"]
        await self.confirm_attempt_deletion()
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),2)
        for name in ("Четвёртая", "Пятая"):
            await self.send("2", name+" 6A")
            await self.process("ai", record_intent(name=name,grade="6A"))
        tid=await self.conn.scalar(select(RouteAttempt.training_id).where(RouteAttempt.route_snapshot["name"].astext=="Четвёртая"))
        await self.send("2", "tr:"+tid, True)
        await self.process()
        await self.send("2", "am:select", True)
        await self.process()
        await self.send("2", "am:all", True)
        await self.process()
        await self.send("2", "am:askdelete", True)
        await self.process()
        await self.send("2", "am:delete:"+old_confirmation, True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),4)
        await self.confirm_attempt_deletion()
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),2)
        await self.send("2", "tr:"+initial[0].training_id, True)
        await self.process()
        await self.send("2", "am:pick:"+initial[0].id, True)
        await self.process()
        await self.send("2", "am:askdelete", True)
        await self.process()
        await self.confirm_attempt_deletion()
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),1)  # Chosen completed attempt is deleted too.

    async def test_training_choice_region_sector_and_llm_delete_completed_attempt(self):
        from app.public_schemas import AttemptChanges
        await self.login("2")
        await self.login("3")
        attempts=[]
        for name in ("Старая трасса", "Новая трасса"):
            await self.send("2","training:start",True)
            await self.process()
            await self.send("2",name+" 6A")
            await self.process("ai",record_intent(name=name,grade="6A"))
            row=(await self.conn.execute(select(RouteAttempt.id,RouteAttempt.training_id).where(
                RouteAttempt.route_snapshot["name"].astext==name))).one()
            attempts.append(row)
            await self.send("2","training:finish",True)
            await self.process()
        await self.send("2","trainings:0",True)
        await self.process()
        await self.send("3","tr:"+attempts[0].training_id,True)
        await self.process()
        await self.send("2","tr:"+attempts[0].training_id,True)
        await self.process()
        overview = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        self.assertIn("Статус: завершена", overview["text"])
        self.assertIn("Регион: Test region", overview["text"])
        self.assertIn("Секторы: Test sector", overview["text"])
        self.assertIn("1 трасс · 1 попыток", overview["text"])
        self.assertIn("С зависанием: 1 попыток", overview["text"])
        self.assertTrue(any(button["callback_data"]=="am:pick:"+attempts[0].id for row in overview["reply_markup"]["inline_keyboard"] for button in row))
        await self.send("2","am:pick:"+attempts[0].id,True)
        await self.process()
        await self.send("2","Измени район на Крым и сектор на Красный камень")
        await self.process("ai",Intent(kind="update_attempts",changes=AttemptChanges(region="Крым",sector="Красный камень")))
        snapshot=await self.conn.scalar(select(RouteAttempt.route_snapshot).where(RouteAttempt.id==attempts[0].id))
        from app.models import Location, Section
        self.assertEqual(await self.conn.scalar(select(Location.name).where(Location.id==snapshot["areaId"])),"Крым")
        self.assertEqual(await self.conn.scalar(select(Section.name).where(Section.id==snapshot["sectorId"])),"Красный камень")
        other=await self.conn.scalar(select(RouteAttempt.route_snapshot).where(RouteAttempt.id==attempts[1].id))
        self.assertEqual(await self.conn.scalar(select(Location.name).where(Location.id==other["areaId"])),"Test region")
        await self.send("2","am:pick:"+attempts[0].id,True)
        await self.process()
        editor=(await self.conn.scalar(select(DialogState.data).where(DialogState.state=="attempt_edit")))["editor_token"]
        await self.send("2","am:field:"+editor+":sector",True)
        await self.process()
        await self.send("2","Новый сектор")
        await self.process()
        snapshot=await self.conn.scalar(select(RouteAttempt.route_snapshot).where(RouteAttempt.id==attempts[0].id))
        self.assertEqual(await self.conn.scalar(select(Section.name).where(Section.id==snapshot["sectorId"])),"Новый сектор")
        await self.send("2","Удали выбранный пролаз")
        await self.process("ai",Intent(kind="delete_attempts"))
        await self.confirm_attempt_deletion()
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),1)
        self.assertEqual(await self.conn.scalar(select(RouteAttempt.id)),attempts[1].id)
        owner = await self.login("2")
        version = await self.conn.scalar(select(TrainingSession.version).where(TrainingSession.id==attempts[1].training_id))
        marked = await self.client.patch("/api/v1/attempts/"+attempts[1].id, headers=owner,
            json={"expected_version":version, "is_test":True})
        self.assertEqual(marked.status_code, 200, marked.text)
        await self.send("2", "tr:"+attempts[1].training_id, True)
        await self.process()
        overview = await self.conn.scalar(select(Outbox.payload).where(Outbox.dedupe_key.like("job:%")).order_by(Outbox.sequence.desc()).limit(1))
        self.assertIn("0 трасс · 0 попыток", overview["text"])
        self.assertIn("Тестовых записей: 1", overview["text"])
        self.assertTrue(any(button["callback_data"]=="am:pick:"+attempts[1].id for row in overview["reply_markup"]["inline_keyboard"] for button in row))

    async def test_edit_uses_saved_version_and_foreign_button_is_rejected(self):
        from app.public_schemas import AttemptChanges
        a=await self.login("2")
        await self.login("3")
        await self.send("2","training:start",True)
        await self.process()
        await self.send("2","Трасса 6A")
        await self.process("ai",record_intent(name="Трасса",grade="6A"))
        aid=await self.conn.scalar(select(RouteAttempt.id))
        await self.send("3","am:pick:"+aid,True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),1)
        await self.send("2","training:finish",True)
        await self.process()
        await self.send("2","Измени все пролазы последней тренировки на 6B")
        training=(await self.conn.execute(select(TrainingSession.id,TrainingSession.version))).one()
        response=await self.client.patch("/api/v1/attempts/"+aid,headers=a,
            json={"expected_version":training.version,"grade":"6C"})
        self.assertEqual(response.status_code,200,response.text)
        await self.process("ai",Intent(kind="update_attempts",training_scope="last",target_all=True,changes=AttemptChanges(grade="6B")))
        self.assertEqual((await self.conn.scalar(select(RouteAttempt.route_snapshot)))["grade"],"6C")

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
            json={"worker_id": "ai", "intent": record_intent(name="Трасса", grade="6B", style="flash").model_dump(mode="json")})
        self.assertEqual(late.status_code, 409)
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)

    async def test_attempt_commits_once_and_delivery_failure_does_not_repeat_it(self):
        await self.login("2")
        await self.send("2", "training:start", True)
        await self.process()
        await self.send("2", "Трасса 6B флеш, один срыв")
        item = await self.process("ai", record_intent(name="Трасса", grade="6B", style="flash", falls=1, reached_top=True))
        rows = (await self.conn.execute(select(RouteAttempt))).all()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].clean_ascent)
        self.assertEqual(rows[0].style, "with_falls")
        retry = await self.client.post(f"/api/v1/internal/jobs/ai/{item['id']}/complete", headers={"X-API-Key": "test-auth-key"},
             json={"worker_id": "worker", "intent": record_intent(name="Трасса", grade="6B").model_dump(mode="json")})
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
        await self.start_at_test_location(a)
        for text, callback in (("attempt:form", True), ("Трасса", False), ("6B", False),
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
