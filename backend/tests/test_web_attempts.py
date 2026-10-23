from datetime import date
import unittest
from sqlalchemy import func, insert, select
from app.models import Location, Section, Route, RouteAttempt, TrainingSession
from tests import test_auth_postgres as fixtures


class WebAttemptTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.AuthPostgresTest.asyncSetUp
    asyncTearDown = fixtures.AuthPostgresTest.asyncTearDown
    login = fixtures.AuthPostgresTest.login

    def command(self, **changes):
        return {"date": "2026-10-23", "region": "Гейкбаири", "sector": "Кебап", "name": "Engesh",
                "grade": "6а+", "reached_top": True, "clean_ascent": False, "style": "with_hangs",
                "belay": "lead", "hangs": 2, **changes}

    async def test_create_training_private_catalogue_and_replay_without_duplicates(self):
        headers = {**await self.login("901"), "Idempotency-Key": "web-once"}
        for _ in range(2):
            response = await self.client.post("/api/v1/web-attempts", headers=headers, json=self.command())
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["attempt"]["route_snapshot"]["grade"], "6A+")
        for model in (Location, Section, Route, RouteAttempt, TrainingSession):
            self.assertEqual(await self.conn.scalar(select(func.count()).select_from(model)), 1)
        self.assertEqual(await self.conn.scalar(select(Location.visibility)), "private")
        # A stale form tries to start another training after a concurrent start.
        # Catalogue creation happens first but must roll back with that conflict.
        conflict = await self.client.post("/api/v1/web-attempts", headers={k:v for k,v in headers.items() if k != "Idempotency-Key"},
            json=self.command(region="Другой район", sector="Другой сектор", name="Другая"))
        self.assertEqual(conflict.status_code, 409, conflict.text)
        self.assertEqual(await self.conn.scalar(select(func.count(Location.id))), 1)
        current = await self.client.post("/api/v1/web-attempts", headers={k:v for k,v in headers.items() if k != "Idempotency-Key"},
            json=self.command(training_id=response.json()["trainingId"], region="Другой район", sector="Другой сектор", name="Другая"))
        self.assertEqual(current.status_code, 201, current.text)
        self.assertEqual(await self.conn.scalar(select(func.count(TrainingSession.id))), 1)
        other = await self.login("902")
        foreign = await self.client.post("/api/v1/web-attempts", headers=other,
            json=self.command(training_id=response.json()["trainingId"]))
        self.assertEqual(foreign.status_code, 404)

    async def test_new_route_under_public_sector_uses_private_copy(self):
        headers = await self.login("901")
        await self.conn.execute(insert(Location).values(id="public", name="Гейкбаири", type="outdoor", visibility="public"))
        await self.conn.execute(insert(Section).values(id="sector", location_id="public", name="Кебап", type="sector"))
        response = await self.client.post("/api/v1/web-attempts", headers=headers,
            json=self.command(location_id="public", section_id="sector"))
        self.assertEqual(response.status_code, 201, response.text)
        self.assertNotEqual(response.json()["attempt"]["route_snapshot"]["areaId"], "public")
        self.assertEqual(await self.conn.scalar(select(func.count(Route.id)).where(Route.section_id == "sector")), 0)

    async def test_rejected_attempt_rolls_back_new_catalogue_and_training(self):
        headers = await self.login("901")
        response = await self.client.post("/api/v1/web-attempts", headers=headers,
            json=self.command(belay="unknown"))
        self.assertEqual(response.status_code, 422)
        for model in (Location, TrainingSession, RouteAttempt):
            self.assertEqual(await self.conn.scalar(select(func.count()).select_from(model)), 0)
        await self.conn.execute(insert(TrainingSession).values(id="ended", user_id=(await self.client.get("/api/v1/me",headers=headers)).json()["id"],
            status="completed", local_date=date(2026,10,23), timezone="Europe/Moscow", environment="outdoor"))
        response = await self.client.post("/api/v1/web-attempts", headers=headers, json=self.command(training_id="ended"))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(await self.conn.scalar(select(func.count(Location.id))), 0)
