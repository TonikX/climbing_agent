import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from app.attempt_outcome import normalized_style, outcome, validated_belay
from app.tool_service import _summary


class OutcomeTest(unittest.TestCase):
    def test_clean_correction_establishes_reaching_top_without_overriding_explicit_failure(self):
        current = SimpleNamespace(reached_top=False, clean_ascent=False, falls=0, hangs=0, style="unknown", notes=None)
        self.assertTrue(outcome({"cleanAscent": True}, current)["reached_top"])
        self.assertTrue(outcome({"cleanAscent": True}, current)["clean_ascent"])
        self.assertFalse(outcome({"cleanAscent": True, "reachedTop": False}, current)["clean_ascent"])

    def test_independent_facts_and_legacy_uncertainty(self):
        self.assertIsNone(outcome({"reachedTop": True})["clean_ascent"])
        self.assertEqual(outcome({"cleanAscent": True})["reached_top"], True)
        self.assertEqual(outcome({"reachedTop": False})["clean_ascent"], False)
        self.assertEqual(outcome({"reachedTop": True, "falls": 2})["clean_ascent"], False)
        self.assertEqual(outcome({"result": "send", "style": "flash"})["clean_ascent"], True)
        self.assertFalse(outcome({"style": "redpoint", "reachedTop": True, "notes": "Долез с перерывом"})["clean_ascent"])
        self.assertEqual(normalized_style({"style": "redpoint", "reachedTop": True, "notes": "Долез с перерывом"}), "unknown")
        self.assertFalse(outcome({"style": "flash", "reachedTop": True, "falls": 1})["clean_ascent"])
        self.assertTrue(outcome({"style": "onsight", "notes": "Без срывов и зависаний"})["clean_ascent"])
        for raw in ({"reachedTop": "yes"},):
            with self.assertRaises(HTTPException):
                outcome(raw)

    def test_corrections_preserve_omitted_facts_and_reject_unknown(self):
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

    def test_explicit_corrections_override_clean_style_and_validate_input(self):
        current = SimpleNamespace(reached_top=True, clean_ascent=True, falls=0, style="flash", notes=None)
        for raw, expected in (({"reachedTop": False}, False), ({"cleanAscent": False}, False)):
            self.assertEqual(outcome(raw, current)["clean_ascent"], expected)
            self.assertEqual(normalized_style(raw, current), "not_reached" if raw.get("reachedTop") is False else "unknown")
        self.assertFalse(outcome({"reachedTop": False}, current)["reached_top"])
        for raw in ({"style": "flash", "reachedTop": "yes"}, {"style": "flash", "cleanAscent": "yes"}):
            with self.assertRaises(HTTPException):
                outcome(raw)

    def test_note_negations_do_not_hide_actual_falls(self):
        for notes in ("Срывов не было", "Не было срывов и зависаний", "Не сорвался, не зависал"):
            self.assertTrue(outcome({"style": "flash", "falls": 0, "notes": notes})["clean_ascent"])
        self.assertFalse(outcome({"style": "flash", "reachedTop": True, "falls": 1, "notes": "Срывов не было"})["clean_ascent"])
        self.assertFalse(outcome({"style": "flash", "reachedTop": True, "notes": "Без срывов, но завис на верёвке"})["clean_ascent"])

    def test_clean_styles_infer_zero_counters_without_erasing_evidence(self):
        from app.attempt_outcome import with_clean_counters, infer_facts
        from app.attempt_capture import clear_inferred
        for style in ("redpoint", "flash", "onsight"):
            for raw in ({"style":style}, {"style":style, "falls":None, "hangs":None}):
                resolved = with_clean_counters(raw)
                self.assertEqual((resolved["falls"], resolved["hangs"]), (0, 0))
            contradictory = {"style":style, "falls":2}
            self.assertEqual(with_clean_counters(contradictory), contradictory)
            self.assertFalse(outcome(contradictory)["clean_ascent"])
        facts = {"style":"flash"}
        infer_facts(facts)
        self.assertEqual((facts["falls"], facts["hangs"]), (0, 0))
        clear_inferred(facts)
        facts["style"] = "with_hangs"
        infer_facts(facts)
        self.assertNotIn("falls", facts)
        self.assertNotIn("hangs", facts)
