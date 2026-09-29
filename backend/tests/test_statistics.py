import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.tool_service import (_grade_rank, _summary, _period_summary, _grade_breakdown,
                              _progress_periods, _comparison, _statistics)


def attempt(key, sequence, result="send", style="unknown", is_test=False):
    return SimpleNamespace(id=str(sequence), route_session_key=key, sequence=sequence,
                           reached_top=result == "send", clean_ascent=result == "send",
                           style=style, is_test=is_test, attempts=1,
                           belay="lead",
                           route_snapshot={"grade": "6B"}, route=None)


class StatisticsTest(unittest.TestCase):
    def test_split_grade_is_not_concatenated_into_a_two_digit_grade(self):
        self.assertLess(_grade_rank("6B/6B+"), _grade_rank("7A"))

    def test_styles_count_first_success_per_route_and_exclude_projects_and_tests(self):
        summary = _summary([
            attempt("a", 1, style="flash"), attempt("a", 2, style="redpoint"),
            attempt("b", 3, result="project", style="redpoint"),
            attempt("c", 4, style="onsight"), attempt("d", 5),
            attempt("e", 6, style="flash", is_test=True),
        ])
        self.assertEqual(summary["completedRoutes"], 3)
        self.assertEqual(summary["flashCount"], 1)
        self.assertEqual(summary["onsightCount"], 1)
        self.assertEqual(summary["redpointCount"], 0)
        self.assertEqual(summary["unknownStyleCount"], 1)
        self.assertEqual(summary["attemptsCount"], 5)
        self.assertEqual(summary["leadAttemptsCount"], 5)


def graded(key, sequence, grade, clean=False, top=False, test=False):
    item = attempt(key, sequence, is_test=test)
    item.route_snapshot = {"grade": grade}
    item.clean_ascent, item.reached_top = clean, top or clean
    return item


def training(key, day, minutes=None):
    return SimpleNamespace(id=key, local_date=date.fromisoformat(day), duration_minutes=minutes,
                           started_at=None, completed_at=None)


class ExtendedStatisticsTest(unittest.TestCase):
    def test_maxima_rates_and_session_counts(self):
        summary = _summary([
            graded("a", 1, "7A"), graded("b", 2, "6C"),
            graded("b", 3, "6C", clean=True), graded("c", 4, "6C+", top=True),
            graded("test", 5, "9A", clean=True, test=True),
        ])
        self.assertEqual(summary["maxAttemptedGrade"], "7A")
        self.assertEqual(summary["maxGrade"], "7A")
        self.assertEqual(summary["maxReachedTopGrade"], "6C+")
        self.assertEqual(summary["maxCompletedGrade"], "6C")
        self.assertEqual(summary["routesCount"], 3)
        self.assertEqual(summary["attemptsCount"], 4)
        self.assertAlmostEqual(summary["completionRate"], 1 / 3)
        self.assertAlmostEqual(summary["attemptsPerRoute"], 4 / 3)
        self.assertEqual(summary["attemptsPerCompletedRoute"], 4)

    def test_empty_and_unsent_have_no_efficiency_denominator(self):
        empty = _summary([])
        self.assertEqual(empty["completionRate"], 0)
        self.assertIsNone(empty["attemptsPerRoute"])
        self.assertIsNone(empty["maxCompletedGrade"])
        self.assertIsNone(_summary([graded("a", 1, "7A")])["attemptsPerCompletedRoute"])

    def test_breakdown_numeric_sort_and_unknown_last(self):
        groups = _grade_breakdown([
            graded("a", 1, "6B/6B+", clean=True), graded("a", 2, "6B/6B+"),
            graded("b", 3, "7A"), graded("c", 4, None),
            graded("test", 5, "9A", test=True),
        ])
        self.assertEqual([g["grade"] for g in groups], ["7A", "6B/6B+", "Без категории"])
        self.assertEqual(groups[1]["routesCount"], 1)
        self.assertEqual(groups[1]["attemptsCount"], 2)
        self.assertEqual(groups[1]["completionRate"], 1)

    def test_duration_counts_unique_real_trainings(self):
        t = training("a", "2026-09-01", 90)
        rows = [(t, graded("a", 1, "6A")), (t, graded("b", 2, "6A")),
                (training("b", "2026-09-02"), graded("c", 3, "6A")),
                (training("test", "2026-09-03", 1000), graded("d", 4, "9A", test=True))]
        summary = _period_summary(rows)
        self.assertEqual(summary["durationMinutes"], 90)
        self.assertEqual(summary["trainingsCount"], 2)

    def test_progress_six_nonempty_months_and_grade_comparison(self):
        rows = [(training(str(m), f"2026-{m:02}-01", 60),
                 graded(str(m), m, "6C+" if m < 9 else "7A", clean=True)) for m in range(1, 10)]
        rows.append((training("test", "2026-10-01"), graded("test", 10, "9A", test=True)))
        periods = _progress_periods(rows)
        self.assertEqual([p["period"] for p in periods], [f"2026-{m:02}" for m in range(9, 3, -1)])
        self.assertEqual(periods[0]["comparison"]["maxCompletedGrade"], "up")
        self.assertEqual(periods[0]["durationMinutes"], 60)
        self.assertIsNone(_comparison({"maxCompletedGrade": "7A"}, {})["maxCompletedGrade"])
        self.assertEqual(_comparison({"maxCompletedGrade": "6C+"},
                                     {"maxCompletedGrade": "7A"})["maxCompletedGrade"], "down")


class PeriodStatisticsTest(unittest.IsolatedAsyncioTestCase):
    async def test_month_uses_previous_calendar_month_and_full_summary(self):
        current = [(training("jan", "2026-01-04", 80), graded("a", 1, "7A", clean=True))]
        previous = [(training("dec", "2025-12-31", 90), graded("b", 2, "6C+", clean=True))]
        with patch("app.tool_service._user", AsyncMock(return_value=SimpleNamespace(id="u"))), \
             patch("app.tool_service._today", return_value=date(2026, 1, 10)), \
             patch("app.tool_service._statistics_rows", AsyncMock(side_effect=[current, previous])) as rows:
            result = await _statistics(None, {"user": {}, "scope": "month"})
        self.assertEqual(rows.await_args_list[1].args[2:], (date(2025, 12, 1), date(2025, 12, 31)))
        self.assertEqual(result["previousPeriod"]["durationMinutes"], 90)
        self.assertEqual(result["previousPeriod"]["maxCompletedGrade"], "6C+")
        self.assertEqual(result["grades"][0]["grade"], "7A")
        self.assertEqual(result["comparison"]["maxCompletedGrade"], "up")
