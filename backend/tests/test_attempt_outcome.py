import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from app.attempt_outcome import normalized_style, outcome
from app.tool_service import _summary


class OutcomeTest(unittest.TestCase):
    def test_independent_facts_and_legacy_uncertainty(self):
        self.assertEqual(outcome({"reachedTop": True})["clean_ascent"], None)
        self.assertEqual(outcome({"cleanAscent": True})["reached_top"], True)
        self.assertEqual(outcome({"reachedTop": False})["clean_ascent"], False)
        self.assertEqual(outcome({"reachedTop": True, "falls": 2})["clean_ascent"], False)
        self.assertEqual(outcome({"result": "send", "style": "flash"})["clean_ascent"], True)
        self.assertFalse(outcome({"style": "redpoint", "notes": "Долез с перерывом"})["clean_ascent"])
        self.assertEqual(normalized_style({"style": "redpoint", "notes": "Долез с перерывом"}), "unknown")
        self.assertFalse(outcome({"style": "flash", "falls": 1})["clean_ascent"])
        self.assertTrue(outcome({"style": "onsight", "notes": "Без срывов и зависаний"})["clean_ascent"])
        for raw in ({"reachedTop": "yes"},):
            with self.assertRaises(HTTPException):
                outcome(raw)

    def test_corrections_preserve_omitted_facts_and_allow_unknown(self):
        item = SimpleNamespace(reached_top=True, clean_ascent=True, falls=0)
        self.assertTrue(outcome({"notes": "updated"}, item)["clean_ascent"])
        self.assertFalse(outcome({"falls": 1}, item)["clean_ascent"])
        self.assertIsNone(outcome({"cleanAscent": None}, item)["clean_ascent"])

    def test_statistics_only_count_confirmed_clean_styles(self):
        attempts = [SimpleNamespace(id=str(i), route_session_key=str(i), sequence=i,
                    reached_top=True, clean_ascent=clean, style="flash", is_test=False,
                    attempts=1, belay="lead", route_snapshot={}, route=None)
                    for i, clean in enumerate([True, False, None])]
        summary = _summary(attempts)
        self.assertEqual(summary["reachedTopRoutes"], 3)
        self.assertEqual(summary["completedRoutes"], 1)
        self.assertEqual(summary["flashCount"], 1)
        self.assertEqual(summary["unknownCleanRoutes"], 1)
        self.assertEqual(summary["activeProjects"], 2)
