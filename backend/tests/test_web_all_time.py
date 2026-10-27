import unittest
from tests import test_auth_postgres as fixtures

class AllTimeTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.AuthPostgresTest.asyncSetUp
    asyncTearDown = fixtures.AuthPostgresTest.asyncTearDown
    login = fixtures.AuthPostgresTest.login

    async def test_all_time_includes_old_training_and_preserves_grade_filter(self):
        headers = await self.login("901")
        for day, grade in (("2025-01-01", "6A"), ("2026-10-27", "6B")):
            training = await self.client.post("/api/v1/trainings", headers=headers, json={"date":day})
            self.assertEqual(training.status_code, 201, training.text)
            tid = training.json()["id"]
            attempt = await self.client.post(f"/api/v1/trainings/{tid}/attempts", headers=headers,
                json={"name":"Route", "grade":grade, "style":"flash", "belay":"lead"})
            self.assertEqual(attempt.status_code, 201, attempt.text)
            ended = await self.client.post(f"/api/v1/trainings/{tid}/finish", headers=headers, json={})
            self.assertEqual(ended.status_code, 200, ended.text)
        response = await self.client.get("/api/v1/statistics/all", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        dto = response.json()
        self.assertEqual((dto["trainingsCount"], dto["routesCount"]), (2, 2))
        self.assertIsNone(dto["dateFrom"])
        self.assertIsNone(dto["dateTo"])
        self.assertEqual({g["grade"] for g in dto["grades"]}, {"6A", "6B"})
        response = await self.client.get("/api/v1/statistics/all?grade=6A", headers=headers)
        self.assertEqual(response.json()["routesCount"], 1)
