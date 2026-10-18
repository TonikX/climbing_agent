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
    def test_unknown_snapshot_grade_does_not_follow_catalogue_edits(self):
        item = attempt("historical", 1)
        item.route_snapshot = {"grade": None}
        item.route = SimpleNamespace(grade="7A")
        self.assertIsNone(_summary([item])["maxAttemptedGrade"])
        item.route_snapshot = {"grade": "6B"}
        self.assertEqual(_summary([item])["maxAttemptedGrade"], "6B")

    def test_split_grade_is_not_concatenated_into_a_two_digit_grade(self):
        self.assertLess(_grade_rank("6B/6B+"), _grade_rank("7A"))
        ordered = ["6B", "6B/6B+", "6B+", "6C"]
        self.assertEqual(sorted(reversed(ordered), key=_grade_rank), ordered)
        self.assertEqual(_grade_rank("6B+/6B"), _grade_rank("6B/6B+"))
        self.assertEqual(_grade_rank("6B/6B"), _grade_rank("6B"))

    def test_split_grade_does_not_override_higher_clean_maximum(self):
        attempts = [graded("a", 1, "6B+", clean=True), graded("b", 2, "6B/6B+", clean=True)]
        for values in (attempts, list(reversed(attempts))):
            summary = _summary(values)
            for key in ("maxAttemptedGrade", "maxReachedTopGrade", "maxCompletedGrade"):
                self.assertEqual(summary[key], "6B+")
            self.assertEqual([g["grade"] for g in _grade_breakdown(values)], ["6B+", "6B/6B+"])
        self.assertEqual(_comparison({"maxCompletedGrade": "6B+"},
                                     {"maxCompletedGrade": "6B/6B+"})["maxCompletedGrade"], "up")

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
    def test_clean_and_top_maxima_use_only_attempts_with_that_outcome(self):
        # Editing the historical grade on one attempt must not upgrade another send.
        values = [graded("same", 1, "6A", clean=True), graded("same", 2, "7A")]
        summary = _summary(values)
        self.assertEqual(summary["maxAttemptedGrade"], "7A")
        self.assertEqual(summary["maxReachedTopGrade"], "6A")
        self.assertEqual(summary["maxCompletedGrade"], "6A")

    def test_cyrillic_grade_letters_have_same_rank_as_latin(self):
        self.assertEqual(_grade_rank("6С+"), _grade_rank("6C+"))
        self.assertEqual(_grade_rank("6В/6В+"), _grade_rank("6B/6B+"))

    def test_equivalent_grade_spellings_share_one_breakdown_bucket(self):
        groups = _grade_breakdown([graded("a", 1, "6A"), graded("b", 2, "6a"), graded("c", 3, "6а")])
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["routesCount"], 3)

    def test_normalization_preserves_snapshot_and_merges_reversed_split(self):
        values = [graded("a", 1, "6в+ / 6в", clean=True), graded("b", 2, "6B/6B+")]
        groups = _grade_breakdown(values)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["grade"], "6B/6B+")
        self.assertEqual(values[0].route_snapshot["grade"], "6в+ / 6в")

    def test_compact_format_keeps_all_grade_rows_and_omits_zero_styles(self):
        from app.telegram_format import statistics
        values = [graded(str(i), i, "6A", clean=True) for i in range(3)]
        dto = {"scope": "grades", **_summary(values), "grades": _grade_breakdown(values)}
        output = statistics(dto)
        self.assertIn("Категория | трасс | попыток | чисто", output)
        self.assertIn("6A | 3 | 3 | 3 (100%)", output)
        self.assertNotIn("Flash: 0", output)
        self.assertLess(len(output.splitlines()), 13)

    def test_belay_partition_weighted_counts_and_all_test_input(self):
        values = [graded(str(i), i, "6A", clean=i % 2 == 0) for i in range(5)]
        for i, (item, belay) in enumerate(zip(values, ("lead", "top_rope", "auto_belay", "bouldering", "unknown")), 1):
            item.belay, item.attempts = belay, i
        summary = _summary(values)
        self.assertEqual(summary["attemptsCount"], 15)
        self.assertEqual(sum(summary[k] for k in ("leadAttemptsCount", "topRopeAttemptsCount",
            "autoBelayAttemptsCount", "boulderingAttemptsCount", "unknownBelayAttemptsCount")), 15)
        self.assertEqual(summary["completedRoutes"] + summary["activeProjects"], summary["routesCount"])
        for item in values:
            item.is_test = True
        self.assertEqual(_summary(values), _summary([]))

    def test_formatter_shows_duration_efficiency_and_comparison(self):
        from app.telegram_format import statistics
        value = {"scope": "month", "durationMinutes": 90, "completionRate": .5,
                 "attemptsPerRoute": 2, "attemptsPerCompletedRoute": 4,
                 "comparison": {"completedRoutes": "up"}}
        formatted = statistics(value)
        self.assertIn("50%", formatted)
        self.assertTrue("90" in formatted or "1 ч 30" in formatted)
        self.assertIn("↑", formatted)

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
    async def test_leap_month_week_year_boundary_and_end_only(self):
        cases = [
            ({"scope": "month", "dateFrom": "2024-02-01"}, date(2024, 2, 1), date(2024, 2, 29)),
            ({"scope": "week", "dateTo": "2026-01-01"}, date(2025, 12, 29), date(2026, 1, 1)),
            ({"scope": "month", "dateTo": "2026-09-17"}, date(2026, 9, 1), date(2026, 9, 17)),
        ]
        for filters, start, end in cases:
            with patch("app.tool_service._user", AsyncMock(return_value=SimpleNamespace(id="u"))), \
                 patch("app.tool_service._today", return_value=date(2026, 10, 17)), \
                 patch("app.tool_service._statistics_rows", AsyncMock(return_value=[])) as rows:
                await _statistics(None, {"user": {}, **filters})
                self.assertEqual(rows.await_args_list[0].args[2:], (start, end))

    async def test_explicit_dates_and_filters_apply_to_both_periods(self):
        current = [(training("aug", "2026-08-04"), graded("a", 1, "7A", clean=True))]
        previous = [(training("jul", "2026-07-04"), graded("b", 1, "6A", clean=True)),
                    (training("jul2", "2026-07-05"), graded("c", 2, "7A", clean=True))]
        with patch("app.tool_service._user", AsyncMock(return_value=SimpleNamespace(id="u"))), \
             patch("app.tool_service._today", return_value=date(2026, 10, 5)), \
             patch("app.tool_service._statistics_rows", AsyncMock(side_effect=[current, previous])) as rows:
            result = await _statistics(None, {"user": {}, "scope": "month", "grade": "7A",
                                             "dateFrom": "2026-08-03", "dateTo": "2026-08-31"})
        self.assertEqual(rows.await_args_list[0].args[2:], (date(2026, 8, 3), date(2026, 8, 31)))
        self.assertEqual(rows.await_args_list[1].args[2:], (date(2026, 7, 1), date(2026, 7, 31)))
        self.assertEqual(result["previousPeriod"]["completedRoutes"], 1)
        self.assertEqual(result["previousPeriod"]["maxCompletedGrade"], "7A")

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
