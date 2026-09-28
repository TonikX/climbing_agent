import unittest
from types import SimpleNamespace

from app.tool_service import _grade_rank, _summary


def attempt(key, sequence, result="send", style="unknown", is_test=False):
    return SimpleNamespace(id=str(sequence), route_session_key=key, sequence=sequence,
                           reached_top=result == "send", clean_ascent=result == "send",
                           style=style, is_test=is_test, attempts=1,
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


if __name__ == "__main__":
    unittest.main()
