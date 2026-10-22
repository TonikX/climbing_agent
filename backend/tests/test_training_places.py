"""History paging and statistics agree on saved attempt places, with owner isolation."""
from datetime import date
import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Location, Section, TrainingSession, RouteAttempt, ExternalRef
import test_auth_postgres as auth_tests


class TrainingPlacesTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = auth_tests.AuthPostgresTest.asyncSetUp
    asyncTearDown = auth_tests.AuthPostgresTest.asyncTearDown
    login = auth_tests.AuthPostgresTest.login

    async def history(self):
        headers = await self.login("2")
        await self.login("3")
        async with AsyncSession(bind=self.conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            owner = await session.scalar(select(ExternalRef.user_id).where(ExternalRef.external_id == "2"))
            other = await session.scalar(select(ExternalRef.user_id).where(ExternalRef.external_id == "3"))
            areas = [Location(name=name, region=region, type="outdoor", owner_id=uid)
                for name, region, uid in (("Гейкбаири", "Анталья", owner), ("Скалы", "Кавказ", owner),
                                          ("Тестовый район", "Тестовый регион", owner), ("Чужой район", "Чужой регион", other))]
            session.add_all(areas)
            await session.flush()
            sectors = [Section(name=name, type="sector", location_id=area.id) for name, area in zip(("Кебап", "Магара"), areas)]
            session.add_all(sectors)
            await session.flush()
            trainings = {}
            for key, day, uid, area, attempts in (
                ("mixed", "2026-10-20", owner, areas[0], [(0, "6A", False), (1, "6B", False), (2, "9C", True)]),
                ("second", "2026-10-21", owner, areas[1], [(1, "6C", False)]),
                ("previous", "2026-09-20", owner, areas[0], [(None, "6a", False)]),
                ("old", "2025-01-01", owner, areas[0], [(0, "5A", False)]),
                ("empty", "2026-10-22", owner, areas[0], []),
                ("other", "2026-10-22", other, areas[3], [(3, "9C", False)]),
            ):
                training = TrainingSession(user_id=uid, local_date=date.fromisoformat(day), status="completed",
                    timezone="Europe/Moscow", primary_location_id=area.id, duration_minutes=60)
                session.add(training)
                await session.flush()
                trainings[key] = training.id
                for number, (index, grade, is_test) in enumerate(attempts, 1):
                    snapshot = {"name": key+str(number), "grade": grade, "areaId": areas[index].id if index is not None else None}
                    if index in (0, 1):
                        snapshot["sectorId"] = sectors[index].id
                    session.add(RouteAttempt(training_id=training.id, sequence=number, attempts=1,
                        route_session_key=training.id+str(number), route_snapshot=snapshot, is_test=is_test,
                        reached_top=True, clean_ascent=True, style="flash", belay="lead"))
            await session.flush()
            await session.commit()
        return headers, areas, trainings

    async def test_history_filters_before_paging_and_enriches_actual_places(self):
        headers, areas, ids = await self.history()
        params = {"date_from": "2026-01-01", "date_to": "2026-10-22", "area_id": areas[0].id, "limit": 1}
        response = await self.client.get("/api/v1/trainings", params=params, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        page = response.json()
        item = page["items"][0]
        self.assertEqual(item["id"], ids["mixed"])
        self.assertEqual({p["name"] for p in item["locations"]}, {"Гейкбаири", "Скалы"})
        self.assertEqual(item["grades"], ["6A", "6B"])
        self.assertEqual(item["sectors"], ["Кебап", "Магара"])
        response = await self.client.get("/api/v1/trainings", params={**params, "cursor": page["next_cursor"]}, headers=headers)
        self.assertEqual([t["id"] for t in response.json()["items"]], [ids["previous"]])
        self.assertIsNone(response.json()["next_cursor"])
        # Region and grade must match the same real attempt, not different rows of a mixed training.
        response = await self.client.get("/api/v1/trainings", params={"region": "Анталья", "grade": "6B"}, headers=headers)
        self.assertEqual(response.json()["items"], [])
        response = await self.client.get("/api/v1/trainings", params={"region": "Анталья", "grade": "6а"}, headers=headers)
        self.assertEqual({t["id"] for t in response.json()["items"]}, {ids["mixed"], ids["previous"]})
        response = await self.client.get("/api/v1/trainings", params={"area_id": areas[3].id}, headers=headers)
        self.assertEqual(response.json()["items"], [])
        bad = await self.client.get("/api/v1/trainings", params={"date_from": "2026-10-22", "date_to": "2026-01-01"}, headers=headers)
        self.assertEqual(bad.status_code, 422)
        detail = await self.client.get("/api/v1/trainings/"+ids["mixed"], headers=headers)
        self.assertEqual(detail.json()["grades"], ["6A", "6B"])

    async def test_statistics_and_options_ignore_tests_and_other_accounts(self):
        headers, areas, ids = await self.history()
        self.assertEqual((await self.client.get("/api/v1/training-filters")).status_code, 401)
        options = (await self.client.get("/api/v1/training-filters", headers=headers)).json()
        self.assertEqual(options["regions"], ["Анталья", "Кавказ"])
        self.assertEqual({p["id"] for p in options["areas"]}, {areas[0].id, areas[1].id})
        params = {"date_from": "2026-10-01", "date_to": "2026-10-22", "region": "Анталья"}
        for scope in ("month", "progress", "grades", "locations", "projects", "records", "week"):
            response = await self.client.get("/api/v1/statistics/"+scope, params=params, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["trainingsCount"], 1)
            self.assertEqual(response.json()["attemptsCount"], 1)
            self.assertEqual(response.json()["maxAttemptedGrade"], "6A")
            if scope == "month":
                self.assertEqual(response.json()["previousPeriod"]["trainingsCount"], 1)
                self.assertEqual(response.json()["previousPeriod"]["maxAttemptedGrade"], "6A")
        response = await self.client.get("/api/v1/statistics/month", params={**params, "region": "Кавказ", "area_id": areas[1].id}, headers=headers)
        self.assertEqual(response.json()["attemptsCount"], 2)
        self.assertEqual(response.json()["trainingsCount"], 2)
        self.assertEqual(response.json()["maxAttemptedGrade"], "6C")
        response = await self.client.get("/api/v1/statistics/month", params={**params, "area_id": areas[3].id}, headers=headers)
        self.assertEqual(response.json()["trainingsCount"], 0)
