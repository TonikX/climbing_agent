import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.attempt_capture import complete_facts, save_or_ask
from app.jobs import now
from app.public_schemas import Intent


class AttemptClarificationTest(unittest.IsolatedAsyncioTestCase):
    async def test_partial_answers_keep_known_facts_and_only_ask_missing_fields(self):
        facts = dict(region="Гейкбаири", sector="Кебап", name="Engesh", grade="6A",
                     reached_top=True, clean_ascent=False, style="unknown", belay="unknown")
        training = SimpleNamespace(id="training", primary_location_id=None)
        user = SimpleNamespace(id="user", test_mode_enabled=False)
        session, reply = AsyncMock(), AsyncMock()
        for number, intent, expected in (
            (1, Intent(kind="attempt", style="with_hangs"), ["Страховка"]),
            (2, Intent(kind="clarify", question="Назовите трассу и категорию"), ["Страховка"]),
        ):
            draft = dict(form="attempt_capture", training_id=training.id, token="previous", facts=facts)
            session.get.return_value = SimpleNamespace(data=draft, created_at=now())
            job = SimpleNamespace(id=str(number), training_id=training.id,
                                  payload={"pending_attempt": draft, "command": "с зависанием"})
            with patch("app.attempt_capture._active", AsyncMock(return_value=training)), \
                 patch("app.attempt_capture.place", AsyncMock(return_value={})), \
                 patch("app.catalog_capture.resolve", AsyncMock(return_value=True)), \
                 patch("app.attempt_capture.dialog_set", AsyncMock()) as store:
                await save_or_ask(session, user, job, intent, reply)
            facts = store.call_args.args[3]["facts"]
            text = reply.call_args.args[2]
            self.assertEqual([line.split(":")[0][2:] for line in text.splitlines() if line.startswith("• ")], expected)
            self.assertEqual((facts["name"], facts["region"], facts["sector"], facts["grade"]),
                             ("Engesh", "Гейкбаири", "Кебап", "6A"))
            self.assertFalse(facts["clean_ascent"])
            self.assertEqual(facts["style"], "with_hangs")

    async def test_unknown_style_does_not_erase_known_belay_or_false_outcome(self):
        facts = dict(region="Гейкбаири", sector="Кебап", name="Engesh", grade="6A",
                     reached_top=True, clean_ascent=False, style="unknown", belay="top_rope")
        facts.update(location_id="area", section_id="sector")
        reply, session = AsyncMock(), AsyncMock()
        session.get.return_value = SimpleNamespace(id="saved", data={})
        with patch("app.catalog_capture.resolve", AsyncMock(return_value=True)), \
             patch("app.catalog_capture.private_hierarchy", AsyncMock()), \
             patch("app.attempt_capture.card", AsyncMock(return_value="card")), \
             patch("app.attempt_capture.execute_tool", AsyncMock(return_value={"attemptId":"saved"})) as save:
            await complete_facts(session, SimpleNamespace(id="user"), SimpleNamespace(id="job"),
                                 SimpleNamespace(id="training", local_date=now().date()), facts, reply)
        raw = save.call_args.args[2]["attempt"]
        self.assertEqual(raw["style"], "unknown")
        self.assertEqual(raw["belay"], "top_rope")
        self.assertFalse(raw["cleanAscent"])
        self.assertTrue(reply.call_args.args[2].startswith("Сохранено."))
