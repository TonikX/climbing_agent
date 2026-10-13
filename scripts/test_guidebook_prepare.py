import unittest
from guidebook_prepare import sql_plan


class ImportPlanTest(unittest.TestCase):
    def row(self, **changes):
        return dict(source_sha256="a"*64, row_key="page-004:0:1:600:1", area="Geyikbayırı",
                    sector="Gizlibahçe", name="Test's route", grade="6B+", grade_raw="VII+",
                    page="4", panel="1", reviewed="yes", **changes)

    def test_unreviewed_and_mixed_area_rejected(self):
        row = self.row()
        row["reviewed"] = "no"
        with self.assertRaises(ValueError):
            sql_plan([row], "location_test")
        other = self.row()
        other.update(area="Other area", row_key="other")
        with self.assertRaises(ValueError):
            sql_plan([self.row(), other], "location_test")

    def test_repeat_is_deterministic_and_values_are_quoted(self):
        row = self.row()
        row["name"] = "x'); DELETE FROM users; --"
        sql = sql_plan([row], "location_test")
        self.assertEqual(sql, sql_plan([row], "location_test"))
        self.assertIn("'x''); DELETE FROM users; --'", sql)
        self.assertIn("AND visibility='public' AND owner_id IS NULL", sql)
        self.assertIn("guidebook_antalya_2023", sql)

    def test_roman_grade_must_not_enter_french_grade_column(self):
        row = self.row()
        row["grade"] = "VII+"
        with self.assertRaises(ValueError):
            sql_plan([row], "location_test")


if __name__ == "__main__":
    unittest.main()
