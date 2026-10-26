import unittest
from types import SimpleNamespace
from fastapi import HTTPException
from app.attempt_outcome import outcome, normalized_style, infer_facts
from app.attempt_capture import clear_inferred


class NotReachedTest(unittest.TestCase):
    def test_style_fills_both_outcomes_and_failure_fills_style_even_with_counts(self):
        self.assertEqual(outcome({"style": "not_reached"})["reached_top"], False)
        self.assertEqual(outcome({"style": "not_reached"})["clean_ascent"], False)
        for raw in ({"reachedTop": False}, {"reachedTop": False, "falls": 3, "hangs": 1}):
            self.assertEqual(normalized_style(raw), "not_reached")
        facts = {"reached_top": False}
        infer_facts(facts)
        self.assertEqual((facts["clean_ascent"], facts["style"]), (False, "not_reached"))

    def test_nonclean_does_not_guess_failure_and_clean_does_not_guess_clean_style(self):
        for raw in ({"cleanAscent": False}, {"falls": 1}, {"style": "with_hangs"}):
            self.assertIsNone(outcome(raw, require_complete=False)["reached_top"])
        facts = {"clean_ascent": True}
        infer_facts(facts)
        self.assertTrue(facts["reached_top"])
        self.assertNotIn("style", facts)

    def test_corrections_replace_old_failure_and_explicit_conflicts_are_rejected(self):
        item = SimpleNamespace(reached_top=False, clean_ascent=False, style="not_reached", falls=0, hangs=0, notes=None)
        for raw in ({"reachedTop": True}, {"cleanAscent": True}, {"style": "flash"}):
            self.assertTrue(outcome(raw, item)["reached_top"])
            self.assertNotEqual(normalized_style(raw, item), "not_reached")
        for raw in ({"style": "not_reached", "reachedTop": True}, {"style": "not_reached", "cleanAscent": True}):
            with self.assertRaises(HTTPException):
                outcome(raw)
        facts = {"style": "not_reached"}
        infer_facts(facts)
        clear_inferred(facts)
        facts["style"] = "flash"
        infer_facts(facts)
        self.assertTrue(facts["reached_top"])
        self.assertTrue(facts["clean_ascent"])
