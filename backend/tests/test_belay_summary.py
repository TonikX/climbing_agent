import unittest
from types import SimpleNamespace
from app.statistics_belays import reached_by_belay
from app.tool_service import _summary
from app.public_schemas import StatisticsDTO

class BelaySummaryTest(unittest.TestCase):
    def attempt(self, key, belay="lead", top=True, clean=False, test=False):
        return SimpleNamespace(id=key, route_session_key=key, belay=belay,
            reached_top=top, clean_ascent=clean, is_test=test,
            sequence=1, attempts=3, style="unknown", route_snapshot={}, route=None)

    def test_counts_routes_instead_of_attempts_and_separates_cleanliness(self):
        rows = [self.attempt("a"), self.attempt("a", clean=True), self.attempt("a", clean=True),
                self.attempt("b"), self.attempt("c", clean=None),
                self.attempt("failed", top=False), self.attempt("unknown", top=None),
                self.attempt("test", clean=True, test=True),
                self.attempt("upper", "top_rope", clean=True)]
        result = reached_by_belay(rows)
        self.assertEqual(result["lead"], {"total":3,"clean":1,"nonClean":1,"unknownClean":1})
        self.assertEqual(result["top_rope"], {"total":1,"clean":1,"nonClean":0,"unknownClean":0})
        self.assertEqual(StatisticsDTO.model_validate(_summary(rows)).reachedByBelay["lead"].total, 3)

    def test_each_belay_is_independent_and_empty_period_has_zeroes(self):
        rows = [self.attempt("same", clean=True), self.attempt("same", "top_rope")]
        self.assertEqual(reached_by_belay(rows)["top_rope"]["nonClean"], 1)
        for counts in reached_by_belay([]).values():
            self.assertTrue(all(value == 0 for value in counts.values()))
