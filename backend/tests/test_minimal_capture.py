import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
from app.attempt_fields import missing_fields
from app.attempt_outcome import outcome
from app.telegram_format import reply_menu
from app.manual_clarification import advance
from app.tool_service import _set_test_mode

class MinimalCaptureTest(unittest.IsolatedAsyncioTestCase):
    async def test_minimal_manual_entry_does_not_ask_optional_fields(self):
        facts = {"region":"Area", "sector":"Sector", "grade":"6A", "name": "Unknown route", "belay": "lead"}
        self.assertEqual(missing_fields(facts), [])
        self.assertIsNone(outcome(facts)["clean_ascent"])
        self.assertIsNone(outcome(facts)["reached_top"])
        training = SimpleNamespace(id="t", primary_location_id=None, sections=[])
        with patch("app.attempt_capture.complete_facts", AsyncMock()) as save:
            reply = AsyncMock()
            await advance(AsyncMock(), SimpleNamespace(id="u"), SimpleNamespace(), training, facts, reply)
            save.assert_awaited_once()
            reply.assert_not_awaited()

    async def test_regular_user_cannot_enable_mode_via_tool(self):
        user = SimpleNamespace(role="user", test_mode_enabled=False)
        with patch("app.tool_service._user", AsyncMock(return_value=user)):
            with self.assertRaises(HTTPException) as error:
                await _set_test_mode(AsyncMock(), {"user": {"id": "u"}, "enabled": True})
            self.assertEqual(error.exception.status_code, 403)
            self.assertFalse(user.test_mode_enabled)

    def test_keyboards_hide_home_and_restrict_test_mode(self):
        for admin in (False, True):
            labels = [x["text"] for row in reply_menu(True, admin)["keyboard"] for x in row]
            self.assertNotIn("🏠 Главное меню", labels)
            self.assertEqual("🧪 Тестовый режим" in labels, admin)
        self.assertEqual(missing_fields({"name": "Engesh"}), ["region", "sector", "grade", "belay"])

    def test_unknown_fields_are_not_displayed_as_negative_or_zero(self):
        from app.telegram_format import ascent_card, attempts
        item = SimpleNamespace(route_snapshot={"name":"Engesh"}, is_test=False,
            reached_top=None, clean_ascent=None, style="unknown", belay="lead",
            falls=None, hangs=None, notes=None)
        card = ascent_card(item)
        for label in ("Регион", "Сектор", "Категория", "Дошёл до конца", "Чисто", "Стиль", "Срывы", "Зависания", "Комментарий"):
            self.assertIn(label + ": Неизвестно", card)
        self.assertIn("Страховка: Нижняя", card)
        item.reached_top, item.clean_ascent, item.falls = False, False, 0
        card = ascent_card(item)
        self.assertIn("Дошёл до конца: Нет", card)
        self.assertIn("Срывы: 0", card)
        details = attempts({"routes":[{"name":"Engesh", "belay":"lead"}]})[0]
        self.assertIn("Пролез чисто: Неизвестно", details)
        self.assertIn("Комментарий: Неизвестно", details)

    async def test_manual_missing_catalogue_fields_are_required_but_outcome_is_not(self):
        facts = {"name":"Engesh", "belay":"lead"}
        training = SimpleNamespace(id="t", primary_location_id=None, sections=[])
        with patch("app.attempt_management.dialog_set", AsyncMock()) as store, \
             patch("app.attempt_capture.complete_facts", AsyncMock()) as save:
            await advance(AsyncMock(), SimpleNamespace(id="u"), SimpleNamespace(), training, facts, AsyncMock())
            self.assertEqual(store.call_args.args[2], "region")
            save.assert_not_awaited()
        facts.update(region="Area", sector="Sector", grade="6A")
        self.assertEqual(missing_fields(facts), [])
