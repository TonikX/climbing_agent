import unittest
from types import SimpleNamespace

from app.catalog_capture import grade_key
from app.grades import normalize_grade
from app.public_schemas import Intent, AttemptChanges, RouteWrite
from app.schemas import AttemptCreate
from app.route_input import route_name
from app.telegram_format import ascent_card


class GradeInputTest(unittest.TestCase):
    def test_latin_cyrillic_case_and_split_are_one_grade_on_all_inputs(self):
        for spelling in ("6a", "6а", "6A", "6А", " 6 а "):
            self.assertEqual(normalize_grade(spelling), "6A")
            self.assertEqual(Intent(kind="attempt", grade=spelling).grade, "6A")
            self.assertEqual(AttemptCreate(grade=spelling, belay="lead").grade, "6A")
            self.assertEqual(AttemptChanges(grade=spelling).grade, "6A")
            self.assertEqual(RouteWrite(section_id="s", name="R", grade=spelling).grade, "6A")
            self.assertEqual(grade_key(spelling), "6A")
        self.assertEqual(grade_key("6в+ / 6в"), grade_key("6B/6B+"))

    def test_embedded_card_is_not_stored_or_displayed_as_route_name(self):
        card = ("Регион: Гейкбаири Сектор: magara Название трассы: crying boy "
                "Категория: 6A Чисто: нет Стиль: с зависанием Страховка: верхняя Дошел до конца: да")
        for value in (card, card.replace(" Сектор:", "\nСектор:").replace(" Категория:", "\nКатегория:")):
            self.assertEqual(route_name(value), "crying boy")
            self.assertEqual(Intent(kind="attempt", name=value).name, "crying boy")
            self.assertEqual(AttemptCreate(name=value, belay="lead").name, "crying boy")
            self.assertEqual(AttemptChanges(name=value).name, "crying boy")
        item = SimpleNamespace(route_snapshot={"name":card, "grade":"6а"}, is_test=False,
                               clean_ascent=False, style="with_hangs", belay="top_rope")
        rendered = ascent_card(item, "Гейкбаири", "magara")
        for label in ("Регион:", "Сектор:", "Название трассы:", "Категория:", "Чисто:", "Стиль:", "Страховка:"):
            self.assertEqual(rendered.count(label), 1)
        self.assertIn("Название трассы: crying boy\nКатегория: 6A", rendered)
        self.assertEqual(item.route_snapshot["name"], card)
        self.assertEqual(route_name("Регион: неизвестность"), "Регион: неизвестность")
