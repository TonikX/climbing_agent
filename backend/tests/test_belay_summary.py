import unittest
from types import SimpleNamespace
from app.statistics_belays import reached_by_belay, ascents_by_belay
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

    def test_routes_and_recorded_ascents_are_separate_and_belay_totals_add_up(self):
        rows = [self.attempt("same", clean=True), self.attempt("same", clean=False),
                self.attempt("same", "top_rope", clean=True), self.attempt("failed", top=False),
                self.attempt("unknown", top=None), self.attempt("test", test=True),
                self.attempt("auto", "auto_belay", clean=None), self.attempt("boulder", "bouldering"),
                self.attempt("legacy", None, clean=True)]
        summary = _summary(rows)
        self.assertEqual(summary["routesCount"], 6)
        self.assertEqual(summary["reachedTopRoutes"], 4)
        self.assertEqual(summary["ascentsCount"], 6)
        counts = summary["ascentsByBelay"]
        self.assertEqual(counts["lead"]["total"], 2)
        self.assertEqual(summary["reachedByBelay"]["lead"]["total"], 1)
        self.assertEqual(counts["lead"]["clean"], 1)
        self.assertEqual(counts["lead"]["nonClean"], 1)
        self.assertEqual(sum(item["total"] for item in counts.values()), summary["ascentsCount"])
        for item in counts.values():
            self.assertEqual(item["total"], item["clean"] + item["nonClean"] + item["unknownClean"])
        dto = StatisticsDTO.model_validate(summary)
        self.assertEqual(dto.ascentsCount, 6)
        self.assertEqual(dto.ascentsByBelay["unknown"].total, 1)
        self.assertTrue(all(item["total"] == 0 for item in ascents_by_belay([]).values()))
