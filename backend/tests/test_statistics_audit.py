"""Statistics contract against a small history with hand-calculated totals."""
from datetime import date
from unittest.mock import patch
import unittest

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import test_public_service as public_tests
from app.models import ExternalRef, Location, TrainingSession, RouteAttempt
from app.public_models import Job, Outbox
from app.public_schemas import Intent
from app.telegram_format import statistics


class StatisticsAuditTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUpBase = public_tests.PublicServiceTest.asyncSetUpBase
    asyncTearDownBase = public_tests.PublicServiceTest.asyncTearDownBase
    login = public_tests.PublicServiceTest.login
    send = public_tests.PublicServiceTest.send
    process = public_tests.PublicServiceTest.process

    async def asyncSetUp(self):
        await public_tests.PublicServiceTest.asyncSetUp(self)
        self.clock = patch("app.tool_service._today", return_value=date(2026, 10, 17))
        self.clock.start()
        self.a, self.b = await self.login("2"), await self.login("3")
        async with AsyncSession(bind=self.conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as s:
            uid = await s.scalar(select(ExternalRef.user_id).where(ExternalRef.external_id == "2"))
            other = await s.scalar(select(ExternalRef.user_id).where(ExternalRef.external_id == "3"))
            area = Location(name="Audit area", type="outdoor", owner_id=uid)
            s.add(area)
            await s.flush()
            self.trainings = {}
            for name, day, minutes, status, owner in (
                ("previous", "2026-09-30", 45, "completed", uid),
                ("first", "2026-10-12", 90, "completed", uid),
                ("last", "2026-10-13", 60, "completed", uid),
                ("empty", "2026-10-15", 900, "completed", uid),
                ("test", "2026-10-16", 900, "completed", uid),
                ("active", "2026-10-17", None, "active", uid),
                ("other", "2026-10-17", 900, "completed", other)):
                t = TrainingSession(user_id=owner, local_date=date.fromisoformat(day), status=status,
                    timezone="Europe/Moscow", duration_minutes=minutes,
                    primary_location_id=area.id if owner == uid else None)
                s.add(t)
                await s.flush()
                self.trainings[name] = t.id
            # group, grade, top, clean, style, belay, number of attempts, is_test
            data = {
                "previous": [("z", "5A", True, True, "onsight", "lead", 1, False)],
                "first": [("a", "6A", False, False, "with_falls", "lead", 3, False),
                          ("a", "6A", True, True, "redpoint", "lead", 1, False),
                          ("b", "6B", True, False, "with_hangs", "top_rope", 2, False),
                          ("c", "6B+", True, True, "unknown", "bouldering", 1, False),
                          ("test-mixed", "9C", True, True, "flash", "lead", 10, True)],
                "last": [("d", "6B/6B+", True, True, "flash", "auto_belay", 1, False)],
                "active": [("e", "7A", False, False, "unknown", "lead", 1, False)],
                "test": [("test-only", "9C", True, True, "flash", "lead", 10, True)],
                "other": [("other-user", "9C", True, True, "flash", "lead", 10, False)],
            }
            for name, rows in data.items():
                for seq, (key, grade, top, clean, style, belay, count, test) in enumerate(rows, 1):
                    s.add(RouteAttempt(training_id=self.trainings[name], sequence=seq, route_session_key=key,
                        attempts=count, reached_top=top, clean_ascent=clean, style=style, belay=belay,
                        falls=1 if style == "with_falls" else 0, hangs=1 if style == "with_hangs" else 0,
                        is_test=test, route_snapshot={"name": key, "grade": grade,
                            "areaId": area.id if name != "other" else None}))
            await s.commit()

    async def asyncTearDown(self):
        self.clock.stop()
        await public_tests.PublicServiceTest.asyncTearDown(self)

    async def read(self, scope, **params):
        response = await self.client.get("/api/v1/statistics/" + scope, headers=self.a, params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    async def test_week_month_hand_calculated_totals_and_styles(self):
        for scope in ("week", "month"):
            value = await self.read(scope)
            for key, expected in {"trainingsCount": 3, "routesCount": 5, "attemptsCount": 9,
                "completedRoutes": 3, "reachedTopRoutes": 4, "activeProjects": 2,
                "onsightCount": 0, "flashCount": 1, "redpointCount": 1,
                "topRopeStyleAttemptsCount": 0, "withFallsAttemptsCount": 3, "withHangsAttemptsCount": 2,
                "leadAttemptsCount": 5, "topRopeAttemptsCount": 2, "autoBelayAttemptsCount": 1,
                "boulderingAttemptsCount": 1, "unknownBelayAttemptsCount": 0,
                "maxAttemptedGrade": "7A", "maxReachedTopGrade": "6B+", "maxCompletedGrade": "6B+",
                "durationMinutes": 150, "completionRate": .6, "attemptsPerRoute": 1.8,
                "attemptsPerCompletedRoute": 3}.items():
                self.assertEqual(value[key], expected, (scope, key, value))
        previous = (await self.read("month"))["previousPeriod"]
        self.assertEqual(previous["dateFrom"], "2026-09-01")
        self.assertEqual(previous["dateTo"], "2026-09-30")
        self.assertEqual(previous["onsightCount"], 1)
        self.assertEqual(previous["durationMinutes"], 45)

    async def test_all_lifetime_scopes_exclude_tests_and_other_users(self):
        for scope in ("grades", "locations", "projects", "records", "progress"):
            value = await self.read(scope)
            self.assertEqual(value["trainingsCount"], 4, scope)
            self.assertEqual(value["attemptsCount"], 10, scope)
            self.assertEqual(value["routesCount"], 6, scope)
            self.assertNotIn("9C", str(value))
            self.assertNotIn("test-only", str(value))
        grades = (await self.read("grades"))["grades"]
        self.assertEqual([x["grade"] for x in grades], ["7A", "6B+", "6B/6B+", "6B", "6A", "5A"])
        self.assertEqual(next(x for x in grades if x["grade"] == "6A")["attemptsCount"], 4)
        locations = (await self.read("locations"))["locations"]
        self.assertEqual(len(locations), 1)
        self.assertEqual(locations[0]["attemptsCount"], 10)
        projects = (await self.read("projects"))["projects"]
        self.assertEqual({x["route"]["name"] for x in projects}, {"b", "e"})
        records = (await self.read("records"))["records"]
        self.assertEqual(records["highestCompletedGrade"], "6B+")
        self.assertEqual(records["highestFlashGrade"], "6B/6B+")
        self.assertEqual(records["highestRedpointGrade"], "6A")
        self.assertEqual(records["totalCompletedRoutes"], 4)
        periods = (await self.read("progress"))["periods"]
        self.assertEqual([x["period"] for x in periods], ["2026-10", "2026-09"])
        self.assertEqual(periods[0]["comparison"]["maxCompletedGrade"], "up")

    async def test_current_last_full_details_and_owner_isolation(self):
        current = await self.read("current-training")
        self.assertEqual(current["id"], self.trainings["active"])
        self.assertEqual(current["summary"]["attemptsCount"], 1)
        last = (await self.read("trainings/last", detail="full"))["training"]
        self.assertEqual(last["trainingId"], self.trainings["last"])
        self.assertEqual(len(last["routes"]), 1)
        self.assertEqual(last["routes"][0]["route"]["name"], "d")
        other = await self.client.get("/api/v1/statistics/month", headers=self.b)
        self.assertEqual(other.json()["attemptsCount"], 10)
        self.assertEqual(other.json()["trainingsCount"], 1)

    async def test_dates_grade_filter_empty_and_invalid_ranges(self):
        only = await self.read("month", date_from="2026-10-12", date_to="2026-10-12", grade="6A")
        self.assertEqual(only["trainingsCount"], 1)
        self.assertEqual(only["attemptsCount"], 4)
        self.assertEqual(only["previousPeriod"]["attemptsCount"], 0)
        empty = await self.read("week", date_from="2026-10-14", date_to="2026-10-16")
        self.assertEqual(empty["trainingsCount"], 0)
        self.assertEqual(empty["attemptsCount"], 0)
        self.assertIsNone(empty["maxAttemptedGrade"])
        for params, status in (({"date_from": "2026-10-18", "date_to": "2026-10-17"}, 422),
                               ({"date_from": "bad"}, 400)):
            response = await self.client.get("/api/v1/statistics/month", headers=self.a, params=params)
            self.assertEqual(response.status_code, status, response.text)

    async def test_grade_filter_accepts_cyrillic_equivalent(self):
        value = await self.read("month", grade="6а")
        self.assertEqual(value["attemptsCount"], 4)

    async def test_buttons_use_same_dto_without_ai_and_nl_formats_once(self):
        for scope in ("week", "month", "grades", "locations", "projects", "records", "progress"):
            expected = statistics(await self.read(scope))
            before = await self.conn.scalar(select(func.coalesce(func.max(Outbox.sequence), 0)))
            await self.send("2", "stats:" + scope, True)
            await self.process()
            payloads = list((await self.conn.scalars(select(Outbox.payload).where(
                Outbox.sequence > before).order_by(Outbox.sequence))).all())
            # Callback acknowledgements share the outbox but have no message text.
            payloads = [x for x in payloads if "text" in x]
            self.assertTrue(payloads)
            self.assertTrue(all(len(x["text"]) <= 3500 for x in payloads))
            self.assertEqual("\n".join(x["text"].rstrip() for x in payloads), expected.rstrip())
            if scope in ("grades", "month"):
                self.assertTrue(any(x.get("entities") for x in payloads))
                for payload in payloads:
                    for entity in payload.get("entities", []):
                        self.assertEqual(entity["type"], "pre")
                        self.assertLessEqual(entity["offset"] + entity["length"],
                                             len(payload["text"].encode("utf-16-le")) // 2)
        self.assertEqual(await self.conn.scalar(select(func.count(Job.id)).where(Job.lane == "ai")), 0)
        await self.send("2", "Покажи статистику за месяц")
        await self.process("ai", Intent(kind="statistics", scope="month"))
        self.assertEqual(await self.conn.scalar(select(func.count(Job.id)).where(Job.lane == "ai")), 1)
        payload = await self.conn.scalar(select(Outbox.payload).order_by(Outbox.sequence.desc()).limit(1))
        self.assertEqual(payload["text"], statistics(await self.read("month")))
