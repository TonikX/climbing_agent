import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.manual_clarification import advance, answer


class ManualClarificationTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_missing_belay_then_save_without_full_wizard(self):
        facts = dict(region="Гейкбаири", sector="Кебап", name="Engesh", grade="6A",
                     reached_top=True, clean_ascent=False, style="with_hangs", belay="unknown", hangs=5)
        session, reply = AsyncMock(), AsyncMock()
        user, training = SimpleNamespace(id="user"), SimpleNamespace(id="training")
        job = SimpleNamespace(id="job", payload={"command": "form:lead"})
        with patch("app.attempt_management.dialog_set", AsyncMock()) as store, \
             patch("app.attempt_capture.complete_facts", AsyncMock()) as save:
            await advance(session, user, job, training, facts, reply)
            self.assertEqual(reply.call_args.args[2], "Какая страховка?")
            draft = SimpleNamespace(state=store.call_args.args[2], data=store.call_args.args[3])
            await answer(session, user, job, training, draft, reply)
            save.assert_awaited_once()
            saved = save.call_args.args[4]
            self.assertEqual((saved["belay"], saved["style"], saved["hangs"]), ("lead", "with_hangs", 5))
            self.assertFalse(saved["clean_ascent"])
            self.assertEqual(reply.await_count, 1)

    async def test_false_answers_are_known_and_old_counter_form_can_finish(self):
        user, training = SimpleNamespace(id="user"), SimpleNamespace(id="training")
        data = dict(form="catalog_manual", training_id="training", name="Engesh", grade="6A",
                    reachedTop=False, cleanAscent=False, style="with_falls", belay="lead")
        with patch("app.attempt_capture.complete_facts", AsyncMock()) as save, \
             patch("app.attempt_management.dialog_set", AsyncMock()) as store:
            await answer(AsyncMock(), user, SimpleNamespace(payload={"command": "5"}), training,
                         SimpleNamespace(state="falls", data=data), AsyncMock())
            store.assert_not_awaited()
            self.assertEqual(save.call_args.args[4]["falls"], 5)
            self.assertFalse(save.call_args.args[4]["reached_top"])
